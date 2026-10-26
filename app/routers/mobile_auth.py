import os
import secrets

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.db.session import get_session
from app.manage_staff import hash_password, verify_password
from app.models.entities import AuditLog, AuthSession, ExternalIdentity, User, UserRole
from app.routers.mobile_dependencies import (
    DUMMY_PASSWORD_HASH,
    _auth_response,
    _rate_limit,
    _session_digest,
    require_mobile_user,
)
from app.routers.sso import _has_legacy_google_sign_in
from app.schemas.mobile import (
    AuthResponse,
    ChangePasswordRequest,
    GoogleSsoRequest,
    LoginRequest,
    ProfileUpdateRequest,
    ProfileUserResponse,
    RegisterRequest,
    SuccessResponse,
)
from app.security import add_record_history

router = APIRouter()


@router.post(
    "/auth/register",
    dependencies=[Depends(_rate_limit("mobile-register", 5, 3600))],
    response_model=AuthResponse,
)
def register(
    body: RegisterRequest,
    request: Request,
    session: Session = Depends(get_session),
):
    if len(body.password.encode("utf-8")) > 1024:
        raise HTTPException(status_code=400, detail="Password is too long.")
    email = body.email.strip().lower()
    full_name = body.full_name.strip()
    local_part, separator, domain = email.partition("@")
    if (
        not full_name
        or not separator
        or not local_part
        or "." not in domain
        or any(character.isspace() for character in email)
    ):
        raise HTTPException(
            status_code=400, detail="A valid name and email are required."
        )
    if session.exec(select(User).where(User.email == email)).first():
        raise HTTPException(
            status_code=409, detail="An account with that email already exists."
        )
    user = User(
        full_name=full_name,
        email=email,
        hashed_password=hash_password(body.password),
        role=UserRole.USER,
    )
    session.add(user)
    try:
        session.flush()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(
            status_code=409, detail="An account with that email already exists."
        ) from exc
    request.state.mobile_user = user
    add_record_history(session, request, "user", user.id, "mobile_account_registered")
    response = _auth_response(session, user, "Account created.")
    session.commit()
    return response


@router.post(
    "/auth/login",
    dependencies=[Depends(_rate_limit("mobile-login", 5, 900))],
    response_model=AuthResponse,
)
def login(
    body: LoginRequest,
    request: Request,
    session: Session = Depends(get_session),
):
    email = body.email.strip().lower()
    user = session.exec(select(User).where(User.email == email)).first()
    password_valid = verify_password(
        body.password, user.hashed_password if user else DUMMY_PASSWORD_HASH
    )
    if (
        not user
        or not user.is_active
        or user.role != UserRole.USER
        or not password_valid
    ):
        raise HTTPException(status_code=401, detail="Invalid email or password.")
    request.state.mobile_user = user
    add_record_history(session, request, "user", user.id, "mobile_login")
    response = _auth_response(session, user, "Signed in.")
    session.commit()
    return response


@router.post(
    "/auth/google-sso",
    dependencies=[Depends(_rate_limit("mobile-google-sso", 5, 900))],
    response_model=AuthResponse,
)
def google_sso(
    body: GoogleSsoRequest,
    request: Request,
    session: Session = Depends(get_session),
):
    try:
        import firebase_admin
        from firebase_admin import auth, credentials
        from google.auth.exceptions import DefaultCredentialsError
    except ImportError as exc:
        raise HTTPException(
            status_code=503,
            detail="Legacy Google sign-in is unavailable on this server.",
        ) from exc

    project_id = os.environ.get("FIREBASE_PROJECT_ID", "").strip()
    if not project_id:
        raise HTTPException(
            status_code=503,
            detail="Legacy Google sign-in is not configured on this server.",
        )
    try:
        try:
            app = firebase_admin.get_app()
        except ValueError:
            app = firebase_admin.initialize_app(
                credentials.ApplicationDefault(),
                options={"projectId": project_id},
            )
        claims = auth.verify_id_token(body.id_token, app=app, check_revoked=True)
        firebase_user = auth.get_user(
            str(claims.get("uid") or claims.get("sub") or ""),
            app=app,
        )
    except (
        auth.InvalidIdTokenError,
        auth.ExpiredIdTokenError,
        auth.RevokedIdTokenError,
        auth.UserNotFoundError,
    ) as exc:
        raise HTTPException(
            status_code=401, detail="Invalid Google sign-in token."
        ) from exc
    except (
        ValueError,
        DefaultCredentialsError,
        firebase_admin.exceptions.FirebaseError,
    ) as exc:
        raise HTTPException(
            status_code=503, detail="Unable to verify Google sign-in at this time."
        ) from exc

    google_identity = next(
        (
            identity
            for identity in firebase_user.provider_data
            if identity.provider_id == "google.com"
        ),
        None,
    )
    email = str(claims.get("email", "")).strip().lower()
    subject = str(google_identity.uid if google_identity else "")
    if (
        not subject
        or len(subject) > 255
        or not email
        or len(email) > 255
        or email.count("@") != 1
        or claims.get("email_verified") is not True
    ):
        raise HTTPException(
            status_code=401,
            detail="A verified Google identity and email are required.",
        )

    identity = session.exec(
        select(ExternalIdentity).where(
            ExternalIdentity.provider == "google",
            ExternalIdentity.subject == subject,
        )
    ).first()
    user = session.get(User, identity.user_id) if identity else None
    if not identity:
        user = session.exec(select(User).where(User.email == email)).first()
        if user and not _has_legacy_google_sign_in(session, user):
            raise HTTPException(
                status_code=409,
                detail="This email already has an account. Sign in to that account and connect Google.",
            )
        if not user:
            user = User(
                full_name=str(claims.get("name") or email.partition("@")[0])[:200],
                email=email,
                hashed_password=hash_password(secrets.token_urlsafe(48)),
                role=UserRole.USER,
            )
            session.add(user)
            try:
                session.flush()
            except IntegrityError as exc:
                session.rollback()
                raise HTTPException(
                    status_code=409,
                    detail="This email already has an account. Sign in to that account and connect Google.",
                ) from exc
        session.add(
            ExternalIdentity(
                user_id=user.id,
                provider="google",
                subject=subject,
                email=email,
            )
        )
    elif not user or not user.is_active or user.role != UserRole.USER:
        raise HTTPException(status_code=403, detail="This account is unavailable.")
    else:
        identity.email = email
        session.add(identity)

    if not user or not user.is_active or user.role != UserRole.USER:
        raise HTTPException(status_code=403, detail="This account is unavailable.")
    request.state.mobile_user = user
    session.add(
        AuditLog(
            actor_id=user.id,
            actor_identity=user.email,
            action="auth.sso_login_success",
            target_type="user",
            target_id=str(user.id),
            details='{"provider":"google","client":"mobile","legacy":true}',
        )
    )
    add_record_history(session, request, "user", user.id, "mobile_google_login")
    response = _auth_response(session, user, "Signed in.")
    session.commit()
    return response


@router.post(
    "/auth/change-password",
    dependencies=[Depends(_rate_limit("mobile-change-password", 5, 3600))],
    response_model=SuccessResponse,
)
def change_password(
    body: ChangePasswordRequest,
    request: Request,
    user: User = Depends(require_mobile_user),
    session: Session = Depends(get_session),
):
    if body.email.strip().lower() != user.email:
        raise HTTPException(
            status_code=403, detail="You can only change your own password."
        )
    if not verify_password(body.old_password, user.hashed_password):
        raise HTTPException(
            status_code=400, detail="The current password is incorrect."
        )
    if len(body.new_password.encode("utf-8")) > 1024:
        raise HTTPException(status_code=400, detail="The new password is too long.")
    user.hashed_password = hash_password(body.new_password)
    session.add(user)
    authorization = request.headers.get("Authorization", "")
    scheme, _, current_token = authorization.partition(" ")
    if scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="Sign-in required.")
    current_token = current_token.strip()
    session.exec(
        AuthSession.__table__.delete().where(
            AuthSession.user_id == user.id,
            AuthSession.token_hash != _session_digest(current_token),
        )
    )
    add_record_history(session, request, "user", user.id, "mobile_password_changed")
    session.commit()
    return {"success": True, "message": "Password changed."}


@router.post("/auth/logout", response_model=SuccessResponse)
def logout(
    request: Request,
    user: User = Depends(require_mobile_user),
    session: Session = Depends(get_session),
):
    authorization = request.headers.get("Authorization", "")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="Sign-in required.")
    auth_session = session.exec(
        select(AuthSession).where(
            AuthSession.token_hash == _session_digest(token.strip()),
            AuthSession.user_id == user.id,
        )
    ).first()
    if auth_session:
        session.delete(auth_session)
        add_record_history(session, request, "user", user.id, "mobile_logout")
        session.commit()
    return {"success": True, "message": "Signed out."}


@router.get("/auth/profile", response_model=ProfileUserResponse)
def get_mobile_profile(user: User = Depends(require_mobile_user)):
    return {
        "userId": user.id,
        "fullName": user.full_name,
        "email": user.email,
        "role": "Volunteer",
        "phoneNumber": user.phone_number,
        "preferences": user.preferences,
    }


@router.put("/auth/profile", response_model=ProfileUserResponse)
def update_profile(
    body: ProfileUpdateRequest,
    request: Request,
    user: User = Depends(require_mobile_user),
    session: Session = Depends(get_session),
):
    full_name = body.full_name.strip()
    if not full_name:
        raise HTTPException(status_code=400, detail="Full name is required.")
    user.full_name = full_name
    user.phone_number = body.phone_number.strip()
    if "preferences" in body.model_fields_set:
        user.preferences = body.preferences
    session.add(user)
    add_record_history(session, request, "user", user.id, "mobile_profile_updated")
    session.commit()
    session.refresh(user)
    return {
        "userId": user.id,
        "fullName": user.full_name,
        "email": user.email,
        "role": "Volunteer",
        "phoneNumber": user.phone_number,
        "preferences": user.preferences,
    }
