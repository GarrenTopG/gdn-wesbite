import base64
import hashlib
import hmac
import os
import re
import secrets
from datetime import timedelta
import logging
from typing import Any
from urllib.parse import urlencode, urlsplit, urlunsplit

import requests
from authlib.jose import JsonWebToken
from authlib.jose.errors import JoseError
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.db.session import get_session
from app.manage_staff import hash_password
from app.models.entities import (
    AuditLog,
    AuthSession,
    ExternalIdentity,
    MobileSsoCode,
    RecordHistory,
    SsoTransaction,
    User,
    UserRole,
)
from app.routers.accounts import USER_COOKIE_NAME, _safe_next_path, get_public_user
from app.routers.mobile_dependencies import (
    _auth_response,
    _rate_limit,
    _session_digest,
)
from app.schemas.mobile import AuthResponse, SsoExchangeRequest
from app.security import (
    PUBLIC_SESSION_TTL_SECONDS,
    add_record_history,
    enforce_rate_limit,
    now_utc,
    require_csrf,
    secure_cookies,
)

router = APIRouter()
logger = logging.getLogger(__name__)
SSO_TRANSACTION_TTL_SECONDS = 5 * 60
MOBILE_CODE_TTL_SECONDS = 60
MOBILE_REDIRECT_URI_DEFAULT = (
    "https://aurorah-web-hub.onrender.com/mobile-auth/callback"
)
GOOGLE_AUTHORIZATION_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
GOOGLE_JWKS_ENDPOINT = "https://www.googleapis.com/oauth2/v3/certs"
MICROSOFT_AUTHORIZATION_ENDPOINT = (
    "https://login.microsoftonline.com/common/oauth2/v2.0/authorize"
)
MICROSOFT_TOKEN_ENDPOINT = "https://login.microsoftonline.com/common/oauth2/v2.0/token"
MICROSOFT_JWKS_ENDPOINT = "https://login.microsoftonline.com/common/discovery/v2.0/keys"
PROVIDER_PATTERN = re.compile(r"^[A-Za-z0-9_-]{43}$")


class InvalidSsoResponse(Exception):
    pass


class SsoProviderUnavailable(Exception):
    pass


def _has_legacy_google_sign_in(session: Session, user: User) -> bool:
    return bool(
        session.exec(
            select(RecordHistory.id).where(
                RecordHistory.record_type == "user",
                RecordHistory.record_id == user.id,
                RecordHistory.action.in_(
                    ("mobile_account_registered_google", "mobile_google_login")
                ),
            )
        ).first()
    )


def _provider_values(provider: str) -> tuple[str, str]:
    if provider not in {"google", "microsoft"}:
        raise HTTPException(status_code=404, detail="Unknown sign-in provider.")
    prefix = f"SSO_{provider.upper()}"
    client_id = os.environ.get(f"{prefix}_CLIENT_ID", "").strip()
    client_secret = os.environ.get(f"{prefix}_CLIENT_SECRET", "").strip()
    if not client_id and not client_secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"{provider.title()} sign-in is not configured.",
        )
    if not client_id or not client_secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"{provider.title()} sign-in is incompletely configured.",
        )
    base_url = os.environ.get("SSO_BASE_URL", "").strip().rstrip("/")
    parsed_base = urlsplit(base_url)
    if (
        not base_url
        or parsed_base.scheme not in {"https", "http"}
        or not parsed_base.netloc
        or parsed_base.path not in {"", "/"}
        or parsed_base.query
        or parsed_base.fragment
        or parsed_base.username
        or parsed_base.password
        or (
            os.environ.get("APP_ENV", "development").lower() == "production"
            and parsed_base.scheme != "https"
        )
    ):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="SSO_BASE_URL must be configured as the public site origin.",
        )
    return client_id, client_secret


def _callback_uri(provider: str) -> str:
    _provider_values(provider)
    return f"{os.environ['SSO_BASE_URL'].rstrip('/')}/auth/sso/callback/{provider}"


def available_providers() -> list[str]:
    providers = []
    for provider in ("google", "microsoft"):
        if (
            os.environ.get(f"SSO_{provider.upper()}_CLIENT_ID", "").strip()
            and os.environ.get(f"SSO_{provider.upper()}_CLIENT_SECRET", "").strip()
            and os.environ.get("SSO_BASE_URL", "").strip()
        ):
            providers.append(provider)
    return providers


def validate_sso_configuration() -> None:
    for provider in ("google", "microsoft"):
        prefix = f"SSO_{provider.upper()}"
        if (
            os.environ.get(f"{prefix}_CLIENT_ID", "").strip()
            or os.environ.get(f"{prefix}_CLIENT_SECRET", "").strip()
        ):
            try:
                _provider_values(provider)
            except HTTPException as exc:
                raise RuntimeError(str(exc.detail)) from exc


def _authorization_endpoint(provider: str) -> str:
    return (
        GOOGLE_AUTHORIZATION_ENDPOINT
        if provider == "google"
        else MICROSOFT_AUTHORIZATION_ENDPOINT
    )


def _token_endpoint(provider: str) -> str:
    return GOOGLE_TOKEN_ENDPOINT if provider == "google" else MICROSOFT_TOKEN_ENDPOINT


def _jwks_endpoint(provider: str) -> str:
    return GOOGLE_JWKS_ENDPOINT if provider == "google" else MICROSOFT_JWKS_ENDPOINT


def _mobile_redirect_uri() -> str:
    value = os.environ.get(
        "MOBILE_SSO_REDIRECT_URI", MOBILE_REDIRECT_URI_DEFAULT
    ).strip()
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or not parsed.netloc
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="MOBILE_SSO_REDIRECT_URI must be a configured HTTPS app link.",
        )
    return value


def _pkce_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def _state_cookie_name(provider: str) -> str:
    return f"sso_state_{provider}"


def _start_rate_limit(bucket: str, method: str = "GET"):
    def check(request: Request, session: Session = Depends(get_session)) -> None:
        enforce_rate_limit(
            request,
            session,
            bucket,
            20,
            15 * 60,
            methods=(method,),
        )

    return check


def _start_sso(
    *,
    session: Session,
    provider: str,
    client_type: str,
    intent: str = "login",
    next_path: str = "/",
    link_user: User | None = None,
    mobile_challenge: str | None = None,
) -> RedirectResponse:
    client_id, _ = _provider_values(provider)
    now = now_utc()
    session.exec(
        SsoTransaction.__table__.delete().where(SsoTransaction.expires_at < now)
    )
    session.exec(MobileSsoCode.__table__.delete().where(MobileSsoCode.expires_at < now))
    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)
    provider_verifier = secrets.token_urlsafe(64)
    transaction = SsoTransaction(
        state_hash=hashlib.sha256(state.encode("ascii")).hexdigest(),
        provider=provider,
        client_type=client_type,
        intent=intent,
        next_path=_safe_next_path(next_path),
        nonce=nonce,
        provider_code_verifier=provider_verifier,
        mobile_code_challenge=mobile_challenge,
        link_user_id=link_user.id if link_user else None,
        expires_at=now + timedelta(seconds=SSO_TRANSACTION_TTL_SECONDS),
    )
    session.add(transaction)
    session.commit()

    parameters = {
        "client_id": client_id,
        "redirect_uri": _callback_uri(provider),
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "nonce": nonce,
        "code_challenge": _pkce_challenge(provider_verifier),
        "code_challenge_method": "S256",
    }
    if provider == "microsoft":
        parameters["response_mode"] = "query"
    response = RedirectResponse(
        f"{_authorization_endpoint(provider)}?{urlencode(parameters)}",
        status_code=303,
    )
    response.set_cookie(
        key=_state_cookie_name(provider),
        value=state,
        max_age=SSO_TRANSACTION_TTL_SECONDS,
        httponly=True,
        secure=secure_cookies(),
        samesite="lax",
        path="/",
    )
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


@router.get(
    "/account/sso/{provider}",
    dependencies=[Depends(_start_rate_limit("website-sso-start"))],
)
def start_website_sso(
    provider: str,
    next_path: str = "/",
    session: Session = Depends(get_session),
):
    return _start_sso(
        session=session,
        provider=provider,
        client_type="web",
        next_path=next_path,
    )


@router.post(
    "/account/sso/link/{provider}",
    dependencies=[
        Depends(require_csrf),
        Depends(_start_rate_limit("website-sso-link", "POST")),
    ],
)
def start_website_sso_link(
    request: Request,
    provider: str,
    session: Session = Depends(get_session),
):
    user = get_public_user(request, session)
    if not user:
        return RedirectResponse("/account/login", status_code=303)
    return _start_sso(
        session=session,
        provider=provider,
        client_type="web",
        intent="link",
        link_user=user,
    )


@router.get("/api/auth/sso/providers")
def mobile_sso_providers():
    return {"providers": available_providers()}


@router.get(
    "/api/auth/sso/{provider}/start",
    dependencies=[Depends(_start_rate_limit("mobile-sso-start"))],
)
def start_mobile_sso(
    provider: str,
    challenge: str = Query(..., min_length=43, max_length=43),
    session: Session = Depends(get_session),
):
    if not PROVIDER_PATTERN.fullmatch(challenge):
        raise HTTPException(status_code=400, detail="Invalid mobile proof key.")
    _mobile_redirect_uri()
    return _start_sso(
        session=session,
        provider=provider,
        client_type="mobile",
        mobile_challenge=challenge,
    )


def _decode_identity_token(
    provider: str, raw_token: str, expected_nonce: str, client_id: str
) -> dict[str, Any]:
    try:
        keys_response = requests.get(_jwks_endpoint(provider), timeout=(3, 10))
        keys_response.raise_for_status()
        jwks = keys_response.json()
        if not isinstance(jwks, dict) or not isinstance(jwks.get("keys"), list):
            raise SsoProviderUnavailable("Invalid provider key response.")
        claims = JsonWebToken(["RS256"]).decode(raw_token, jwks)
        claims.validate(leeway=60)
    except requests.RequestException as exc:
        raise SsoProviderUnavailable("Provider keys are unavailable.") from exc
    except (ValueError, TypeError, JoseError) as exc:
        raise InvalidSsoResponse("The identity token is invalid.") from exc

    issuer = claims.get("iss")
    if provider == "google":
        valid_issuer = issuer in {
            "https://accounts.google.com",
            "accounts.google.com",
        }
    else:
        tenant_id = str(claims.get("tid", ""))
        valid_issuer = (
            bool(
                re.fullmatch(
                    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
                    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}",
                    tenant_id,
                )
            )
            and isinstance(issuer, str)
            and issuer.casefold()
            == f"https://login.microsoftonline.com/{tenant_id}/v2.0".casefold()
        )
    audience = claims.get("aud")
    valid_audience = (
        audience == client_id
        if isinstance(audience, str)
        else isinstance(audience, list)
        and client_id in audience
        and claims.get("azp") == client_id
    )
    valid_authorized_party = (
        claims.get("azp", client_id) == client_id
        if isinstance(audience, str)
        else valid_audience
    )
    if (
        not valid_issuer
        or not valid_audience
        or not valid_authorized_party
        or not isinstance(claims.get("sub"), str)
        or not claims["sub"]
        or not isinstance(claims.get("nonce"), str)
        or not hmac.compare_digest(claims["nonce"], expected_nonce)
    ):
        raise InvalidSsoResponse("The identity token claims are invalid.")
    issued_at = claims.get("iat")
    expires_at = claims.get("exp")
    not_before = claims.get("nbf", 0)
    now = now_utc().timestamp()
    if (
        not isinstance(issued_at, (int, float))
        or not isinstance(expires_at, (int, float))
        or not isinstance(not_before, (int, float))
        or isinstance(issued_at, bool)
        or isinstance(expires_at, bool)
        or isinstance(not_before, bool)
        or expires_at < now - 60
        or issued_at > now + 60
        or not_before > now + 60
    ):
        raise InvalidSsoResponse("The identity token time claims are invalid.")
    return dict(claims)


def _exchange_and_validate(
    *,
    provider: str,
    code: str,
    transaction: SsoTransaction,
) -> dict[str, Any]:
    client_id, client_secret = _provider_values(provider)
    try:
        response = requests.post(
            _token_endpoint(provider),
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": _callback_uri(provider),
                "client_id": client_id,
                "client_secret": client_secret,
                "code_verifier": transaction.provider_code_verifier,
            },
            timeout=(3, 10),
        )
        response.raise_for_status()
        token_response = response.json()
    except (requests.RequestException, ValueError) as exc:
        raise SsoProviderUnavailable("Provider token exchange failed.") from exc
    if not isinstance(token_response, dict):
        raise SsoProviderUnavailable("Provider returned an invalid token response.")
    id_token = token_response.get("id_token")
    if not isinstance(id_token, str) or not id_token:
        raise InvalidSsoResponse("Provider did not return an identity token.")
    return _decode_identity_token(provider, id_token, transaction.nonce, client_id)


def _email_from_claims(provider: str, claims: dict[str, Any]) -> str:
    if provider == "google" and claims.get("email_verified") is not True:
        raise InvalidSsoResponse("A verified Google email is required.")
    email = str(claims.get("email") or claims.get("preferred_username") or "")
    email = email.strip().lower()
    if (
        len(email) > 255
        or email.count("@") != 1
        or any(character.isspace() for character in email)
    ):
        raise InvalidSsoResponse("The provider did not return a usable email address.")
    return email


def _resolve_identity(
    session: Session,
    *,
    provider: str,
    claims: dict[str, Any],
    transaction: SsoTransaction,
    request: Request,
) -> User:
    subject = str(claims["sub"])
    if len(subject) > 255:
        raise InvalidSsoResponse("The provider subject is invalid.")
    email = _email_from_claims(provider, claims)
    identity = session.exec(
        select(ExternalIdentity).where(
            ExternalIdentity.provider == provider,
            ExternalIdentity.subject == subject,
        )
    ).first()

    if transaction.intent == "link":
        user = get_public_user(request, session)
        if (
            not user
            or user.id != transaction.link_user_id
            or user.role != UserRole.USER
        ):
            raise InvalidSsoResponse("Sign in again before linking this provider.")
        if identity and identity.user_id != user.id:
            raise InvalidSsoResponse(
                "This provider identity is linked to another account."
            )
        if not identity:
            session.add(
                ExternalIdentity(
                    user_id=user.id,
                    provider=provider,
                    subject=subject,
                    email=email,
                )
            )
        session.add(
            AuditLog(
                actor_id=user.id,
                actor_identity=user.email,
                action="auth.sso_identity_linked",
                target_type="user",
                target_id=str(user.id),
                details=f'{{"provider":"{provider}"}}',
            )
        )
        session.commit()
        return user

    if identity:
        user = session.get(User, identity.user_id)
        if not user or not user.is_active or user.role != UserRole.USER:
            raise InvalidSsoResponse("This account is unavailable.")
        identity.email = email
        session.add(identity)
        return user

    existing = session.exec(select(User).where(User.email == email)).first()
    if existing:
        if (
            provider == "google"
            and existing.is_active
            and existing.role == UserRole.USER
            and _has_legacy_google_sign_in(session, existing)
        ):
            session.add(
                ExternalIdentity(
                    user_id=existing.id,
                    provider=provider,
                    subject=subject,
                    email=email,
                )
            )
            return existing
        raise InvalidSsoResponse(
            "This email already has an account. Sign in to that account and connect "
            "the provider from the account menu."
        )
    name = str(claims.get("name") or email.partition("@")[0]).strip()
    user = User(
        full_name=name[:200] or email.partition("@")[0],
        email=email,
        hashed_password=hash_password(secrets.token_urlsafe(48)),
        role=UserRole.USER,
    )
    session.add(user)
    session.flush()
    session.add(
        ExternalIdentity(
            user_id=user.id,
            provider=provider,
            subject=subject,
            email=email,
        )
    )
    return user


def _mobile_callback_url(code: str | None = None, *, error: bool = False) -> str:
    base = _mobile_redirect_uri()
    parts = urlsplit(base)
    query = []
    if code:
        query.append(("code", code))
    if error:
        query.append(("error", "signin_failed"))
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), ""))


def _callback_failure(transaction: SsoTransaction | None):
    if transaction and transaction.client_type == "mobile":
        return RedirectResponse(_mobile_callback_url(error=True), status_code=303)
    return RedirectResponse("/account/login?sso_error=1", status_code=303)


@router.get("/auth/sso/callback/{provider}")
def sso_callback(
    request: Request,
    provider: str,
    state: str = "",
    code: str = "",
    error: str = "",
    session: Session = Depends(get_session),
):
    if provider not in {"google", "microsoft"}:
        raise HTTPException(status_code=404, detail="Unknown sign-in provider.")
    cookie_state = request.cookies.get(_state_cookie_name(provider), "")
    state_hash = hashlib.sha256(state.encode("utf-8")).hexdigest()
    transaction = session.exec(
        select(SsoTransaction).where(SsoTransaction.state_hash == state_hash)
    ).first()
    if (
        not transaction
        or transaction.provider != provider
        or not state
        or not cookie_state
        or not hmac.compare_digest(state, cookie_state)
    ):
        return _callback_failure(None)

    expires_at = transaction.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=now_utc().tzinfo)
    if expires_at <= now_utc() or error or not code:
        session.delete(transaction)
        session.commit()
        response = _callback_failure(transaction)
        response.delete_cookie(
            _state_cookie_name(provider), secure=secure_cookies(), path="/"
        )
        return response

    try:
        claims = _exchange_and_validate(
            provider=provider, code=code, transaction=transaction
        )
        user = _resolve_identity(
            session,
            provider=provider,
            claims=claims,
            transaction=transaction,
            request=request,
        )
    except InvalidSsoResponse:
        session.delete(transaction)
        session.commit()
        response = _callback_failure(transaction)
        response.delete_cookie(
            _state_cookie_name(provider), secure=secure_cookies(), path="/"
        )
        return response
    except SsoProviderUnavailable as exc:
        logger.warning("SSO provider exchange failed for %s: %s", provider, exc)
        session.delete(transaction)
        session.commit()
        response = _callback_failure(transaction)
        response.delete_cookie(
            _state_cookie_name(provider), secure=secure_cookies(), path="/"
        )
        return response
    except IntegrityError:
        session.rollback()
        failed_transaction = session.exec(
            select(SsoTransaction).where(SsoTransaction.state_hash == state_hash)
        ).first()
        if failed_transaction:
            session.delete(failed_transaction)
            session.commit()
        response = _callback_failure(transaction)
        response.delete_cookie(
            _state_cookie_name(provider), secure=secure_cookies(), path="/"
        )
        return response

    if transaction.intent == "link":
        session.delete(transaction)
        session.commit()
        response = RedirectResponse("/", status_code=303)
    elif transaction.client_type == "web":
        token = secrets.token_urlsafe(32)
        session.add(
            AuthSession(
                token_hash=_session_digest(token),
                user_id=user.id,
                expires_at=now_utc() + timedelta(seconds=PUBLIC_SESSION_TTL_SECONDS),
                mfa_verified=True,
            )
        )
        session.delete(transaction)
        session.add(
            AuditLog(
                actor_id=user.id,
                actor_identity=user.email,
                action="auth.sso_login_success",
                target_type="user",
                target_id=str(user.id),
                details=f'{{"provider":"{provider}","client":"web"}}',
            )
        )
        request.state.public_user = user
        add_record_history(session, request, "user", user.id, "web_sso_login")
        session.commit()
        response = RedirectResponse(transaction.next_path, status_code=303)
        response.set_cookie(
            key=USER_COOKIE_NAME,
            value=token,
            max_age=PUBLIC_SESSION_TTL_SECONDS,
            httponly=True,
            secure=secure_cookies(),
            samesite="lax",
            path="/",
        )
    else:
        if not transaction.mobile_code_challenge:
            session.delete(transaction)
            session.commit()
            response = _callback_failure(transaction)
        else:
            code_value = secrets.token_urlsafe(32)
            session.add(
                MobileSsoCode(
                    code_hash=hashlib.sha256(code_value.encode("ascii")).hexdigest(),
                    user_id=user.id,
                    code_challenge=transaction.mobile_code_challenge,
                    expires_at=now_utc() + timedelta(seconds=MOBILE_CODE_TTL_SECONDS),
                )
            )
            session.delete(transaction)
            session.add(
                AuditLog(
                    actor_id=user.id,
                    actor_identity=user.email,
                    action="auth.sso_login_success",
                    target_type="user",
                    target_id=str(user.id),
                    details=f'{{"provider":"{provider}","client":"mobile"}}',
                )
            )
            add_record_history(session, request, "user", user.id, "mobile_sso_login")
            session.commit()
            response = RedirectResponse(
                _mobile_callback_url(code_value), status_code=303
            )

    response.delete_cookie(
        _state_cookie_name(provider),
        secure=secure_cookies(),
        httponly=True,
        samesite="lax",
        path="/",
    )
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


@router.post(
    "/api/auth/sso/exchange",
    dependencies=[Depends(_rate_limit("mobile-sso-exchange", 10, 900))],
    response_model=AuthResponse,
)
def exchange_mobile_sso_code(
    body: SsoExchangeRequest,
    request: Request,
    session: Session = Depends(get_session),
):
    code_hash = hashlib.sha256(body.code.encode("ascii")).hexdigest()
    handoff = session.exec(
        select(MobileSsoCode).where(MobileSsoCode.code_hash == code_hash)
    ).first()
    if not handoff or handoff.consumed_at:
        raise HTTPException(status_code=401, detail="Invalid or expired sign-in code.")
    expires_at = handoff.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=now_utc().tzinfo)
    if expires_at <= now_utc() or not hmac.compare_digest(
        _pkce_challenge(body.code_verifier), handoff.code_challenge
    ):
        raise HTTPException(status_code=401, detail="Invalid or expired sign-in code.")
    result = session.execute(
        update(MobileSsoCode)
        .where(
            MobileSsoCode.id == handoff.id,
            MobileSsoCode.consumed_at.is_(None),
            MobileSsoCode.expires_at > now_utc(),
        )
        .values(consumed_at=now_utc())
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        session.rollback()
        raise HTTPException(status_code=401, detail="Invalid or expired sign-in code.")
    user = session.get(User, handoff.user_id)
    if not user or not user.is_active or user.role != UserRole.USER:
        session.rollback()
        raise HTTPException(status_code=401, detail="This account is unavailable.")
    request.state.mobile_user = user
    response = _auth_response(session, user, "Signed in.")
    add_record_history(session, request, "user", user.id, "mobile_sso_session_issued")
    session.commit()
    return response
