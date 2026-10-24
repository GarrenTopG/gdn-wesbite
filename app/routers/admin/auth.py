import hashlib
from datetime import timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlmodel import Session, select

from app.db.session import get_session
from app.models.entities import (
    AuthSession,
    AuditLog,
    User,
    UserRole,
)
from app.security import (
    STAFF_COOKIE_NAME,
    STAFF_SESSION_TTL_SECONDS,
    MFA_CHALLENGE_TTL_SECONDS,
    enforce_login_rate_limit,
    enforce_rate_limit,
    add_audit_event,
    create_staff_mfa_challenge,
    matching_totp_counter,
    now_utc,
    require_csrf,
    secure_cookies,
)
from app.templatesconfig import templates
from app.manage_staff import hash_password, verify_password

router = APIRouter(
    dependencies=[Depends(require_csrf), Depends(enforce_login_rate_limit)]
)
DUMMY_PASSWORD_HASH = hash_password("invalid staff account password")


def _session_digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def get_staff_user(request: Request, session: Session) -> Optional[User]:
    token = request.cookies.get(STAFF_COOKIE_NAME)
    if not token:
        return None

    active_session = session.exec(
        select(AuthSession).where(AuthSession.token_hash == _session_digest(token))
    ).first()
    if not active_session or not active_session.mfa_verified:
        return None
    expires_at = active_session.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at <= now_utc():
        return None

    user = session.get(User, active_session.user_id)
    if not user or not user.is_active or user.role == UserRole.USER:
        return None
    return user


def require_staff(request: Request, session: Session = Depends(get_session)) -> User:
    user = get_staff_user(request, session)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Staff sign-in required."
        )
    request.state.staff_user = user
    return user


def require_admin(request: Request, session: Session = Depends(get_session)) -> User:
    user = require_staff(request, session)
    if user.role != UserRole.ADMINISTRATOR:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Administrator role required.",
        )
    return user


def verify_staff_session(request: Request) -> bool:
    return isinstance(getattr(request.state, "staff_user", None), User)


def get_pending_auth_session(
    request: Request, session: Session
) -> Optional[AuthSession]:
    token = request.cookies.get(STAFF_COOKIE_NAME)
    if not token:
        return None
    pending = session.exec(
        select(AuthSession).where(AuthSession.token_hash == _session_digest(token))
    ).first()
    if not pending or pending.mfa_verified:
        return None
    expires_at = pending.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    user = session.get(User, pending.user_id)
    if (
        expires_at <= now_utc()
        or not user
        or not user.is_active
        or user.role == UserRole.USER
    ):
        return None
    return pending


@router.get("/login", response_class=HTMLResponse)
def get_admin_login():
    return RedirectResponse(url="/account/login", status_code=303)


@router.post("/login", response_class=HTMLResponse)
def post_admin_login(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    session: Session = Depends(get_session),
):
    normalized_email = email.strip().lower()
    user = session.exec(select(User).where(User.email == normalized_email)).first()
    password_valid = verify_password(
        password, user.hashed_password if user else DUMMY_PASSWORD_HASH
    )
    if (
        not user
        or not user.is_active
        or user.role == UserRole.USER
        or not password_valid
    ):
        session.add(
            AuditLog(
                actor_identity=user.email if user else "unknown",
                action="auth.login_failed",
                target_type="user" if user else "authentication",
                target_id=str(user.id) if user else None,
            )
        )
        session.commit()
        return templates.TemplateResponse(
            request=request,
            name="adminlogin.html",
            status_code=status.HTTP_401_UNAUTHORIZED,
            context={
                "active_page": "admin",
                "error": "Invalid email or password.",
            },
        )

    token = create_staff_mfa_challenge(session, user)
    session.commit()

    response = RedirectResponse(url="/admin/mfa", status_code=303)
    response.set_cookie(
        key=STAFF_COOKIE_NAME,
        value=token,
        max_age=MFA_CHALLENGE_TTL_SECONDS,
        httponly=True,
        secure=secure_cookies(),
        samesite="lax",
        path="/",
    )
    return response


@router.get("/mfa", response_class=HTMLResponse)
def get_mfa_setup(request: Request, session: Session = Depends(get_session)):
    pending = get_pending_auth_session(request, session)
    if not pending:
        if get_staff_user(request, session):
            return RedirectResponse(url="/admin/dashboard", status_code=303)
        return RedirectResponse(url="/admin/login", status_code=303)
    setup_secret = pending.mfa_setup_secret
    return templates.TemplateResponse(
        request=request,
        name="adminmfa.html",
        context={
            "active_page": "admin",
            "setup_secret": setup_secret,
            "setup_secret_display": (
                " ".join(
                    setup_secret[index : index + 4]
                    for index in range(0, len(setup_secret), 4)
                )
                if setup_secret
                else None
            ),
            "error": None,
        },
        headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"},
    )


@router.post("/mfa/verify")
def verify_mfa(
    request: Request,
    code: str = Form(...),
    session: Session = Depends(get_session),
):
    pending = get_pending_auth_session(request, session)
    if not pending:
        response = RedirectResponse(url="/admin/login", status_code=303)
        response.delete_cookie(
            key=STAFF_COOKIE_NAME,
            secure=secure_cookies(),
            httponly=True,
            samesite="lax",
            path="/",
        )
        return response

    enforce_rate_limit(request, session, "admin-mfa", 5, 15 * 60)
    user = session.get(User, pending.user_id)
    secret = pending.mfa_setup_secret or (user.mfa_secret if user else None)
    matched_counter = matching_totp_counter(secret, code) if secret else None
    if (
        not user
        or matched_counter is None
        or (
            user.mfa_last_counter is not None
            and matched_counter <= user.mfa_last_counter
        )
    ):
        return templates.TemplateResponse(
            request=request,
            name="adminmfa.html",
            status_code=status.HTTP_401_UNAUTHORIZED,
            context={
                "active_page": "admin",
                "setup_secret": pending.mfa_setup_secret,
                "error": "The authenticator code is invalid or has already been used.",
            },
            headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"},
        )

    if pending.mfa_setup_secret:
        user.mfa_secret = pending.mfa_setup_secret
    user.mfa_last_counter = matched_counter
    pending.mfa_verified = True
    pending.mfa_setup_secret = None
    pending.expires_at = now_utc() + timedelta(seconds=STAFF_SESSION_TTL_SECONDS)
    session.add(user)
    session.add(pending)
    session.commit()
    response = RedirectResponse(url="/admin/dashboard", status_code=303)
    response.set_cookie(
        key=STAFF_COOKIE_NAME,
        value=request.cookies[STAFF_COOKIE_NAME],
        max_age=STAFF_SESSION_TTL_SECONDS,
        httponly=True,
        secure=secure_cookies(),
        samesite="lax",
        path="/",
    )
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


@router.post("/mfa/cancel")
def cancel_mfa(
    request: Request,
    session: Session = Depends(get_session),
):
    pending = get_pending_auth_session(request, session)
    if pending:
        session.delete(pending)
        session.commit()
    response = RedirectResponse(url="/admin/login", status_code=303)
    response.delete_cookie(
        key=STAFF_COOKIE_NAME,
        secure=secure_cookies(),
        httponly=True,
        samesite="lax",
        path="/",
    )
    return response


@router.post("/logout", dependencies=[Depends(require_staff)])
def admin_logout(
    request: Request,
    session: Session = Depends(get_session),
):
    token = request.cookies.get(STAFF_COOKIE_NAME)
    if token:
        active_session = session.exec(
            select(AuthSession).where(AuthSession.token_hash == _session_digest(token))
        ).first()
        if active_session:
            add_audit_event(
                session, request, "auth.logout", "user", active_session.user_id
            )
            session.delete(active_session)
            session.commit()
    response = RedirectResponse(url="/admin/login", status_code=303)
    response.delete_cookie(
        key=STAFF_COOKIE_NAME,
        secure=secure_cookies(),
        httponly=True,
        samesite="lax",
        path="/",
    )
    return response
