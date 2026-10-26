import hashlib
import secrets
from datetime import timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Form, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.db.session import get_session
from app.manage_staff import hash_password, verify_password
from app.models.entities import AuditLog, AuthSession, User, UserRole
from app.security import (
    STAFF_COOKIE_NAME,
    MFA_CHALLENGE_TTL_SECONDS,
    PUBLIC_SESSION_TTL_SECONDS,
    add_record_history,
    create_staff_mfa_challenge,
    enforce_rate_limit,
    now_utc,
    require_csrf,
    secure_cookies,
)
from app.templatesconfig import templates

router = APIRouter(
    prefix="/account",
    tags=["Accounts"],
    dependencies=[Depends(require_csrf)],
)
USER_COOKIE_NAME = "user_session"
DUMMY_PASSWORD_HASH = hash_password("invalid public account password")


def _session_digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _safe_next_path(path: str) -> str:
    if not path.startswith("/") or path.startswith("//") or "\\" in path:
        return "/"
    if path.startswith(("/account/", "/admin/")):
        return "/"
    return path


def get_public_user(request: Request, session: Session) -> Optional[User]:
    token = request.cookies.get(USER_COOKIE_NAME)
    if not token:
        return None
    auth_session = session.exec(
        select(AuthSession).where(AuthSession.token_hash == _session_digest(token))
    ).first()
    if not auth_session:
        return None
    expires_at = auth_session.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=now_utc().tzinfo)
    if expires_at <= now_utc():
        return None
    user = session.get(User, auth_session.user_id)
    if not user or not user.is_active or user.role != UserRole.USER:
        return None
    return user


def _render_account(
    request: Request,
    *,
    mode: str,
    next_path: str = "/",
    error: Optional[str] = None,
    full_name: str = "",
    email: str = "",
    status_code: int = status.HTTP_200_OK,
) -> HTMLResponse:
    from app.routers.sso import available_providers

    return templates.TemplateResponse(
        request=request,
        name="account.html",
        status_code=status_code,
        context={
            "active_page": "account",
            "mode": mode,
            "next_path": _safe_next_path(next_path),
            "error": error,
            "full_name": full_name,
            "email": email,
            "sso_providers": available_providers(),
        },
    )


def _account_rate_limit(bucket: str, limit: int, window_seconds: int):
    def check(request: Request, session: Session = Depends(get_session)) -> None:
        enforce_rate_limit(request, session, bucket, limit, window_seconds)

    return check


@router.get("/login", response_class=HTMLResponse)
def account_login_page(
    request: Request,
    next_path: str = "/",
    session: Session = Depends(get_session),
):
    staff_user = _get_staff_user(request, session)
    if staff_user:
        return RedirectResponse("/admin/dashboard", status_code=303)
    user = get_public_user(request, session)
    if user:
        return RedirectResponse(_safe_next_path(next_path), status_code=303)
    return _render_account(
        request,
        mode="login",
        next_path=next_path,
        error=(
            "Sign-in could not be completed. Please try again or use your password."
            if request.query_params.get("sso_error")
            else None
        ),
    )


def _get_staff_user(request: Request, session: Session) -> Optional[User]:
    token = request.cookies.get(STAFF_COOKIE_NAME)
    if not token:
        return None

    auth_session = session.exec(
        select(AuthSession).where(AuthSession.token_hash == _session_digest(token))
    ).first()
    if not auth_session or not auth_session.mfa_verified:
        return None
    expires_at = auth_session.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=now_utc().tzinfo)
    if expires_at <= now_utc():
        return None

    user = session.get(User, auth_session.user_id)
    if not user or not user.is_active or user.role == UserRole.USER:
        return None
    return user


@router.post(
    "/login",
    response_class=HTMLResponse,
    dependencies=[Depends(_account_rate_limit("account-login", 5, 15 * 60))],
)
def account_login(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    next_path: str = Form("/"),
    session: Session = Depends(get_session),
):
    email = email.strip().lower()
    user = session.exec(select(User).where(User.email == email)).first()
    valid_password = verify_password(
        password, user.hashed_password if user else DUMMY_PASSWORD_HASH
    )
    if not user or not user.is_active or not valid_password:
        session.add(
            AuditLog(
                actor_identity=user.email if user else "unknown",
                action="auth.login_failed",
                target_type="user" if user else "authentication",
                target_id=str(user.id) if user else None,
            )
        )
        session.commit()
        return _render_account(
            request,
            mode="login",
            next_path=next_path,
            email=email,
            error="Email or password is incorrect.",
            status_code=status.HTTP_401_UNAUTHORIZED,
        )

    is_staff = user.role != UserRole.USER
    if is_staff:
        token = create_staff_mfa_challenge(session, user)
        session.add(
            AuditLog(
                actor_id=user.id,
                actor_identity=user.email,
                action="auth.login_success",
                target_type="user",
                target_id=str(user.id),
            )
        )
        session.commit()
        response = RedirectResponse("/admin/mfa", status_code=303)
        response.set_cookie(
            key=STAFF_COOKIE_NAME,
            value=token,
            max_age=MFA_CHALLENGE_TTL_SECONDS,
            httponly=True,
            secure=secure_cookies(),
            samesite="lax",
            path="/",
        )
    else:
        token = secrets.token_urlsafe(32)
        session.add(
            AuthSession(
                token_hash=_session_digest(token),
                user_id=user.id,
                expires_at=now_utc() + timedelta(seconds=PUBLIC_SESSION_TTL_SECONDS),
                mfa_verified=True,
            )
        )
        add_record_history(session, request, "user", user.id, "web_login")
        session.commit()
        response = RedirectResponse(_safe_next_path(next_path), status_code=303)
        response.set_cookie(
            key=USER_COOKIE_NAME,
            value=token,
            max_age=PUBLIC_SESSION_TTL_SECONDS,
            httponly=True,
            secure=secure_cookies(),
            samesite="lax",
            path="/",
        )
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


@router.get("/register", response_class=HTMLResponse)
def account_register_page(
    request: Request,
    next_path: str = "/",
    session: Session = Depends(get_session),
):
    user = get_public_user(request, session)
    if user:
        return RedirectResponse(_safe_next_path(next_path), status_code=303)
    return _render_account(request, mode="register", next_path=next_path)


@router.post(
    "/register",
    response_class=HTMLResponse,
    dependencies=[Depends(_account_rate_limit("account-register", 5, 60 * 60))],
)
def account_register(
    request: Request,
    full_name: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    password_confirm: str = Form(...),
    next_path: str = Form("/"),
    session: Session = Depends(get_session),
):
    full_name = full_name.strip()
    email = email.strip().lower()
    next_path = _safe_next_path(next_path)
    local_part, separator, domain = email.partition("@")
    if (
        not full_name
        or len(full_name) > 200
        or not separator
        or not local_part
        or "." not in domain
        or any(character.isspace() for character in email)
    ):
        return _render_account(
            request,
            mode="register",
            next_path=next_path,
            full_name=full_name,
            email=email,
            error="Enter a valid name and email address.",
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    if len(password) < 12 or len(password.encode("utf-8")) > 1024:
        return _render_account(
            request,
            mode="register",
            next_path=next_path,
            full_name=full_name,
            email=email,
            error="Use a password that is at least 12 characters long.",
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    if password != password_confirm:
        return _render_account(
            request,
            mode="register",
            next_path=next_path,
            full_name=full_name,
            email=email,
            error="The passwords do not match.",
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    if session.exec(select(User).where(User.email == email)).first():
        return _render_account(
            request,
            mode="register",
            next_path=next_path,
            full_name=full_name,
            email=email,
            error="An account with that email already exists. Sign in instead.",
            status_code=status.HTTP_409_CONFLICT,
        )

    user = User(
        full_name=full_name,
        email=email,
        hashed_password=hash_password(password),
        role=UserRole.USER,
    )
    session.add(user)
    try:
        session.flush()
    except IntegrityError:
        session.rollback()
        return _render_account(
            request,
            mode="register",
            next_path=next_path,
            full_name=full_name,
            email=email,
            error="An account with that email already exists. Sign in instead.",
            status_code=status.HTTP_409_CONFLICT,
        )

    token = secrets.token_urlsafe(32)
    session.add(
        AuthSession(
            token_hash=_session_digest(token),
            user_id=user.id,
            expires_at=now_utc() + timedelta(seconds=PUBLIC_SESSION_TTL_SECONDS),
            mfa_verified=True,
        )
    )
    add_record_history(session, request, "user", user.id, "web_account_registered")
    session.commit()
    response = RedirectResponse(next_path, status_code=303)
    response.set_cookie(
        key=USER_COOKIE_NAME,
        value=token,
        max_age=PUBLIC_SESSION_TTL_SECONDS,
        httponly=True,
        secure=secure_cookies(),
        samesite="lax",
        path="/",
    )
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


@router.post("/logout")
def account_logout(
    request: Request,
    session: Session = Depends(get_session),
):
    token = request.cookies.get(USER_COOKIE_NAME)
    if token:
        auth_session = session.exec(
            select(AuthSession).where(AuthSession.token_hash == _session_digest(token))
        ).first()
        if auth_session:
            session.delete(auth_session)
            session.commit()
    response = RedirectResponse("/", status_code=303)
    response.delete_cookie(
        key=USER_COOKIE_NAME,
        secure=secure_cookies(),
        httponly=True,
        samesite="lax",
        path="/",
    )
    return response
