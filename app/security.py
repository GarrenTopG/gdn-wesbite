import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from datetime import datetime, timezone
from threading import Lock

from fastapi import Depends, HTTPException, Request, status
from sqlmodel import Session, func, select

from app.db.session import get_session
from app.models.entities import (
    AuditLog,
    RateLimitHit,
    RecordHistory,
    User,
    UserRole,
)

CSRF_COOKIE_NAME = "csrf_token"
STAFF_COOKIE_NAME = "staff_session"
STAFF_SESSION_TTL_SECONDS = 12 * 60 * 60
MFA_CHALLENGE_TTL_SECONDS = 5 * 60
CSRF_TTL_SECONDS = 60 * 60 * 24
_rate_limit_lock = Lock()
ROLE_PERMISSIONS = {
    UserRole.ADMINISTRATOR: frozenset(
        {
            "dashboard",
            "volunteers.read",
            "volunteers.write",
            "beneficiaries.read",
            "beneficiaries.write",
            "needs.read",
            "needs.write",
            "donations.read",
            "donations.write",
            "news.read",
            "news.write",
            "reports.read",
            "exports.read",
            "exports.beneficiaries",
            "exports.volunteers",
            "exports.donations",
            "exports.needs",
            "staff.manage",
            "audit.read",
        }
    ),
    UserRole.CASE_WORKER: frozenset(
        {
            "dashboard",
            "volunteers.read",
            "volunteers.write",
            "beneficiaries.read",
            "beneficiaries.write",
            "needs.read",
            "needs.write",
            "exports.beneficiaries",
            "exports.volunteers",
            "exports.needs",
        }
    ),
    UserRole.FINANCE: frozenset(
        {
            "dashboard",
            "donations.read",
            "donations.write",
            "needs.read",
            "reports.read",
            "exports.read",
            "exports.donations",
            "exports.needs",
        }
    ),
    UserRole.CONTENT_EDITOR: frozenset({"dashboard", "news.read", "news.write"}),
    UserRole.READ_ONLY: frozenset({"dashboard", "reports.read"}),
}


def role_has_permission(role: UserRole, permission: str) -> bool:
    return permission in ROLE_PERMISSIONS.get(role, frozenset())


def permission_required(permission: str):
    async def check_permission(request: Request) -> User:
        user = getattr(request.state, "staff_user", None)
        if not isinstance(user, User):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Staff sign-in required.",
            )
        if not role_has_permission(user.role, permission):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Your staff role does not permit this action.",
            )
        return user

    return check_permission


def add_audit_event(
    session: Session,
    request: Request,
    action: str,
    target_type: str,
    target_id: object = None,
    details: dict[str, object] | None = None,
) -> None:
    actor = getattr(request.state, "staff_user", None)
    session.add(
        AuditLog(
            actor_id=actor.id if isinstance(actor, User) else None,
            actor_identity=actor.email if isinstance(actor, User) else "anonymous",
            action=action,
            target_type=target_type,
            target_id=str(target_id) if target_id is not None else None,
            details=json.dumps(details, sort_keys=True) if details else None,
        )
    )

def add_record_history(
    session: Session,
    request: Request,
    record_type: str,
    record_id: int,
    action: str,
    details: dict[str, object] | None = None,
) -> None:
    actor = getattr(request.state, "staff_user", None)
    session.add(
        RecordHistory(
            record_type=record_type,
            record_id=record_id,
            actor_id=actor.id if isinstance(actor, User) else None,
            action=action,
            details=json.dumps(details, sort_keys=True) if details else None,
        )
    )


def new_totp_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode("ascii").rstrip("=")


def matching_totp_counter(
    secret: str, code: str, timestamp: int | None = None
) -> int | None:
    if len(code) != 6 or not code.isascii() or not code.isdigit():
        return None
    try:
        key = base64.b32decode(secret + "=" * (-len(secret) % 8), casefold=True)
    except (ValueError, base64.binascii.Error):
        return None
    now = int(time.time()) if timestamp is None else timestamp
    for counter in range(max(0, now // 30 - 1), now // 30 + 2):
        digest = hmac.new(key, counter.to_bytes(8, "big"), hashlib.sha1).digest()
        offset = digest[-1] & 0x0F
        value = int.from_bytes(digest[offset : offset + 4], "big") & 0x7FFFFFFF
        expected = f"{value % 1_000_000:06d}"
        if hmac.compare_digest(code, expected):
            return counter
    return None


def valid_totp(secret: str, code: str, timestamp: int | None = None) -> bool:
    return matching_totp_counter(secret, code, timestamp) is not None


def get_secret_key() -> bytes:
    secret = os.environ.get("APP_SECRET_KEY", "")
    if len(secret) < 32:
        raise RuntimeError("APP_SECRET_KEY must contain at least 32 characters.")
    return secret.encode("utf-8")


def secure_cookies() -> bool:
    return os.environ.get("COOKIE_SECURE", "false").lower() == "true"


def validate_security_configuration() -> None:
    get_secret_key()
    if os.environ.get("APP_ENV", "development").lower() == "production" and not secure_cookies():
        raise RuntimeError("COOKIE_SECURE=true is required when APP_ENV=production.")


def make_csrf_token() -> str:
    issued_at = str(int(time.time()))
    nonce = secrets.token_urlsafe(32)
    payload = f"{issued_at}.{nonce}"
    signature = hmac.new(get_secret_key(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}.{signature}"


def valid_csrf_token(token: str) -> bool:
    try:
        issued_at, nonce, signature = token.split(".", 2)
        issued_at_seconds = int(issued_at)
    except (ValueError, TypeError):
        return False
    payload = f"{issued_at}.{nonce}"
    expected = hmac.new(get_secret_key(), payload.encode(), hashlib.sha256).hexdigest()
    age = int(time.time()) - issued_at_seconds
    return (
        bool(nonce)
        and 0 <= age <= CSRF_TTL_SECONDS
        and hmac.compare_digest(signature, expected)
    )


async def require_csrf(request: Request) -> None:
    if request.method in {"GET", "HEAD", "OPTIONS", "TRACE"}:
        return
    cookie_token = request.cookies.get(CSRF_COOKIE_NAME, "")
    submitted_token = request.headers.get("X-CSRF-Token", "")
    if not submitted_token:
        form = await request.form()
        submitted_token = str(form.get("csrf_token", ""))
    if (
        not cookie_token
        or not submitted_token
        or not hmac.compare_digest(cookie_token, submitted_token)
        or not valid_csrf_token(cookie_token)
    ):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid CSRF token.")


def enforce_rate_limit(
    request: Request,
    session: Session,
    bucket: str,
    limit: int,
    window_seconds: int,
) -> None:
    if request.method != "POST":
        return
    client_host = request.client.host if request.client else "unknown"
    client_hash = hmac.new(
        get_secret_key(), client_host.encode("utf-8"), hashlib.sha256
    ).hexdigest()
    bucket_key = f"{bucket}:{client_hash}"
    now = int(time.time())
    cutoff = now - window_seconds

    with _rate_limit_lock:
        session.exec(
            RateLimitHit.__table__.delete().where(RateLimitHit.occurred_at < now - 86400)
        )
        session.add(RateLimitHit(bucket_key=bucket_key, occurred_at=now))
        session.commit()
        count = session.exec(
            select(func.count(RateLimitHit.id)).where(
                RateLimitHit.bucket_key == bucket_key,
                RateLimitHit.occurred_at > cutoff,
            )
        ).one()

    if count > limit:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many submissions. Please try again later.",
            headers={"Retry-After": str(window_seconds)},
        )


def enforce_login_rate_limit(
    request: Request,
    session: Session = Depends(get_session),
) -> None:
    if request.url.path != "/admin/login":
        return
    enforce_rate_limit(request, session, "admin-login", 5, 15 * 60)


def enforce_public_form_rate_limit(
    request: Request,
    session: Session = Depends(get_session),
) -> None:
    enforce_rate_limit(request, session, f"public-form:{request.url.path}", 5, 60 * 60)


def enforce_receipt_rate_limit(
    request: Request,
    session: Session = Depends(get_session),
) -> None:
    enforce_rate_limit(request, session, "receipt-download", 20, 60 * 60)


def csrf_cookie_options() -> dict[str, object]:
    return {
        "httponly": True,
        "secure": secure_cookies(),
        "samesite": "lax",
        "max_age": CSRF_TTL_SECONDS,
        "path": "/",
    }


def now_utc() -> datetime:
    return datetime.now(timezone.utc)
