import hashlib
import secrets
from datetime import timedelta
from typing import Optional

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlmodel import Session, select

from app.db.session import get_session
from app.manage_staff import hash_password
from app.models.entities import AuthSession, User, UserRole
from app.security import MOBILE_SESSION_TTL_SECONDS, enforce_rate_limit, now_utc

bearer_scheme = HTTPBearer(auto_error=False)
DUMMY_PASSWORD_HASH = hash_password("invalid mobile account password")


def _session_digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _user_json(user: User, token: Optional[str] = None) -> dict[str, object]:
    result: dict[str, object] = {
        "userId": user.id,
        "fullName": user.full_name,
        "email": user.email,
        "role": "Volunteer",
    }
    if token:
        result["token"] = token
    return result


def _issue_session(session: Session, user: User) -> str:
    token = secrets.token_urlsafe(32)
    session.add(
        AuthSession(
            token_hash=_session_digest(token),
            user_id=user.id,
            expires_at=now_utc() + timedelta(seconds=MOBILE_SESSION_TTL_SECONDS),
            mfa_verified=True,
        )
    )
    return token


def _auth_response(session: Session, user: User, message: str) -> dict[str, object]:
    token = _issue_session(session, user)
    return {
        "success": True,
        "message": message,
        "token": token,
        "user": _user_json(user),
    }


def require_mobile_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    session: Session = Depends(get_session),
) -> User:
    if not credentials or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Sign-in required."
        )
    auth_session = session.exec(
        select(AuthSession).where(
            AuthSession.token_hash == _session_digest(credentials.credentials)
        )
    ).first()
    if not auth_session:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token."
        )
    expires_at = auth_session.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=now_utc().tzinfo)
    if expires_at <= now_utc():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token."
        )
    user = session.get(User, auth_session.user_id)
    if not user or not user.is_active or user.role != UserRole.USER:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or inactive account.",
        )
    request.state.mobile_user = user
    return user


def _rate_limit(bucket: str, limit: int, window_seconds: int):
    def check(request: Request, session: Session = Depends(get_session)) -> None:
        enforce_rate_limit(request, session, bucket, limit, window_seconds)

    return check
