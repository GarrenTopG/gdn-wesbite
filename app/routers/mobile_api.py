import hashlib
import os
import secrets
from datetime import timedelta
from decimal import Decimal, InvalidOperation
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import true
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.db.session import get_session
from app.manage_staff import hash_password, verify_password
from app.models.entities import (
    AuthSession,
    BeneficiaryNeed,
    Donation,
    DonationStatus,
    NeedStatus,
    NeedUrgency,
    NewsArticle,
    NewsStatus,
    User,
    UserRole,
    Volunteer,
    VolunteerOffer,
    VolunteerStatus,
)
from app.security import (
    STAFF_SESSION_TTL_SECONDS,
    add_record_history,
    enforce_rate_limit,
    now_utc,
)

router = APIRouter(prefix="/api", tags=["Mobile API"])
bearer_scheme = HTTPBearer(auto_error=False)
DUMMY_PASSWORD_HASH = hash_password("invalid mobile account password")


class LoginRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    email: str
    password: str


class RegisterRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    full_name: str = Field(alias="fullName", min_length=1, max_length=200)
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=12, max_length=1024)
    role: Optional[str] = None


class GoogleSsoRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id_token: str = Field(alias="idToken", min_length=1)


class ChangePasswordRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    email: str
    old_password: str = Field(alias="oldPassword", min_length=1, max_length=1024)
    new_password: str = Field(alias="newPassword", min_length=12, max_length=1024)


class OfferAssistanceRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    need_id: int = Field(alias="needId", gt=0)
    user_email: str = Field(alias="userEmail")
    volunteer_skill: str = Field(alias="volunteerSkill", min_length=1, max_length=500)
    notes: str = Field(default="", max_length=2000)


class DonationRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    donation_type: str = Field(default="monetary", alias="donationType", max_length=50)
    category: Optional[str] = Field(default=None, max_length=200)
    amount: Optional[Decimal] = Field(default=None, max_digits=12, decimal_places=2)
    payment_method: Optional[str] = Field(
        default=None, alias="paymentMethod", max_length=100
    )
    user_email: Optional[str] = Field(default=None, alias="userEmail", max_length=320)
    item_category: Optional[str] = Field(
        default=None, alias="itemCategory", max_length=200
    )
    item_description: Optional[str] = Field(
        default=None, alias="itemDescription", max_length=2000
    )
    drop_off_option: Optional[str] = Field(
        default=None, alias="dropOffOption", max_length=50
    )
    logistics_type: Optional[str] = Field(
        default=None, alias="logisticsType", max_length=50
    )
    pickup_address: Optional[str] = Field(
        default=None, alias="pickupAddress", max_length=1000
    )


class ProfileUpdateRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    full_name: str = Field(alias="fullName", min_length=1, max_length=200)
    phone_number: str = Field(alias="phoneNumber", max_length=50)
    preferences: Optional[dict[str, object]] = None


class ProfileUserResponse(BaseModel):
    user_id: int = Field(alias="userId")
    full_name: str = Field(alias="fullName")
    email: str
    role: str
    phone_number: Optional[str] = Field(alias="phoneNumber")
    preferences: Optional[dict[str, object]]

    model_config = ConfigDict(populate_by_name=True)


class MobileUserResponse(BaseModel):
    user_id: int = Field(alias="userId")
    full_name: str = Field(alias="fullName")
    email: str
    role: str

    model_config = ConfigDict(populate_by_name=True)


class AuthResponse(BaseModel):
    success: bool
    message: str
    token: str
    user: MobileUserResponse


class SuccessResponse(BaseModel):
    success: bool
    message: str


class DonationResponse(SuccessResponse):
    transaction_ref: str = Field(alias="transactionRef")

    model_config = ConfigDict(populate_by_name=True)


class NewsItemResponse(BaseModel):
    id: int
    title: str
    summary: str
    image_url: Optional[str] = None
    timestamp: str
    category: str


class NeedResponse(BaseModel):
    need_id: int = Field(alias="needId")
    title: str
    description: str
    location: str
    priority: str
    category: str
    status: str
    created_at: str = Field(alias="createdAt")

    model_config = ConfigDict(populate_by_name=True)


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
            expires_at=now_utc() + timedelta(seconds=STAFF_SESSION_TTL_SECONDS),
            mfa_verified=True,
        )
    )
    return token


def _auth_response(session: Session, user: User, message: str) -> dict[str, object]:
    token = _issue_session(session, user)
    session.commit()
    session.refresh(user)
    return {
        "success": True,
        "message": message,
        "token": token,
        "user": _user_json(user),
    }


async def require_mobile_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    session: Session = Depends(get_session),
) -> User:
    if not credentials or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Sign-in required.")
    auth_session = session.exec(
        select(AuthSession).where(
            AuthSession.token_hash == _session_digest(credentials.credentials)
        )
    ).first()
    if not auth_session:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token.")
    expires_at = auth_session.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=now_utc().tzinfo)
    if expires_at <= now_utc():
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token.")
    user = session.get(User, auth_session.user_id)
    if not user or not user.is_active or user.role != UserRole.USER:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or inactive account.")
    request.state.mobile_user = user
    return user


def _rate_limit(bucket: str, limit: int, window_seconds: int):
    def check(request: Request, session: Session = Depends(get_session)) -> None:
        enforce_rate_limit(request, session, bucket, limit, window_seconds)

    return check


@router.post(
    "/auth/register",
    dependencies=[Depends(_rate_limit("mobile-register", 5, 3600))],
    response_model=AuthResponse,
)
async def register(
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
        raise HTTPException(status_code=400, detail="A valid name and email are required.")
    if session.exec(select(User).where(User.email == email)).first():
        raise HTTPException(status_code=409, detail="An account with that email already exists.")
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
        raise HTTPException(status_code=409, detail="An account with that email already exists.") from exc
    request.state.mobile_user = user
    add_record_history(session, request, "user", user.id, "mobile_account_registered")
    return _auth_response(session, user, "Account created.")


@router.post(
    "/auth/login",
    dependencies=[Depends(_rate_limit("mobile-login", 5, 900))],
    response_model=AuthResponse,
)
async def login(
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
    return _auth_response(session, user, "Signed in.")


@router.post(
    "/auth/google-sso",
    dependencies=[Depends(_rate_limit("mobile-google-sso", 5, 900))],
    response_model=AuthResponse,
)
async def google_sso(
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
            detail="Google sign-in is not configured on this server.",
        ) from exc

    project_id = os.environ.get("FIREBASE_PROJECT_ID", "").strip()
    if not project_id:
        raise HTTPException(status_code=503, detail="Google sign-in is not configured on this server.")
    try:
        try:
            app = firebase_admin.get_app()
        except ValueError:
            app = firebase_admin.initialize_app(
                credentials.ApplicationDefault(),
                options={"projectId": project_id},
            )
        claims = auth.verify_id_token(body.id_token, app=app, check_revoked=True)
    except (auth.InvalidIdTokenError, auth.ExpiredIdTokenError, auth.RevokedIdTokenError) as exc:
        raise HTTPException(status_code=401, detail="Invalid Google sign-in token.") from exc
    except (
        ValueError,
        DefaultCredentialsError,
        firebase_admin.exceptions.FirebaseError,
    ) as exc:
        raise HTTPException(status_code=503, detail="Unable to verify Google sign-in at this time.") from exc

    email = str(claims.get("email", "")).strip().lower()
    full_name = str(claims.get("name", "")).strip()
    if not email or claims.get("email_verified") is not True:
        raise HTTPException(status_code=401, detail="A verified Google email is required.")
    user = session.exec(select(User).where(User.email == email)).first()
    if user and user.role != UserRole.USER:
        raise HTTPException(status_code=403, detail="Staff accounts cannot sign in through the mobile app.")
    if not user:
        user = User(
            full_name=full_name or email.partition("@")[0],
            email=email,
            hashed_password=hash_password(secrets.token_urlsafe(48)),
            role=UserRole.USER,
        )
        session.add(user)
        session.flush()
        request.state.mobile_user = user
        add_record_history(session, request, "user", user.id, "mobile_account_registered_google")
    elif not user.is_active:
        raise HTTPException(status_code=403, detail="This account is inactive.")
    request.state.mobile_user = user
    add_record_history(session, request, "user", user.id, "mobile_google_login")
    return _auth_response(session, user, "Signed in.")


@router.post(
    "/auth/change-password",
    dependencies=[Depends(_rate_limit("mobile-change-password", 5, 3600))],
    response_model=SuccessResponse,
)
async def change_password(
    body: ChangePasswordRequest,
    request: Request,
    user: User = Depends(require_mobile_user),
    session: Session = Depends(get_session),
):
    if body.email.strip().lower() != user.email:
        raise HTTPException(status_code=403, detail="You can only change your own password.")
    if not verify_password(body.old_password, user.hashed_password):
        raise HTTPException(status_code=400, detail="The current password is incorrect.")
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
async def logout(
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


@router.get("/news", response_model=list[NewsItemResponse])
async def get_news(session: Session = Depends(get_session)):
    articles = session.exec(
        select(NewsArticle)
        .where(
            NewsArticle.status == NewsStatus.PUBLISHED.value,
            NewsArticle.archived_at.is_(None),
        )
        .order_by(NewsArticle.created_at.desc())
    ).all()
    return [
        {
            "id": article.id,
            "title": article.title,
            "summary": article.summary,
            "image_url": article.image_url,
            "timestamp": article.created_at.isoformat(),
            "category": article.category,
        }
        for article in articles
    ]


@router.get("/needs", response_model=list[NeedResponse])
async def get_needs(session: Session = Depends(get_session)):
    needs = session.exec(
        select(BeneficiaryNeed)
        .where(
            BeneficiaryNeed.is_community_need == true(),
            BeneficiaryNeed.status.notin_([NeedStatus.FULFILLED, NeedStatus.REJECTED]),
            BeneficiaryNeed.archived_at.is_(None),
        )
        .order_by(BeneficiaryNeed.created_at.desc())
    ).all()
    return [
        {
            "needId": need.id,
            "title": need.anonymised_title,
            "description": need.request_details or "",
            "location": need.area,
            "priority": need.urgency.value,
            "category": need.category,
            "status": need.status.value,
            "createdAt": need.created_at.isoformat(),
        }
        for need in needs
    ]


@router.post(
    "/needs/offer-assistance",
    dependencies=[Depends(_rate_limit("mobile-offer-assistance", 5, 3600))],
    response_model=SuccessResponse,
)
async def offer_assistance(
    body: OfferAssistanceRequest,
    request: Request,
    user: User = Depends(require_mobile_user),
    session: Session = Depends(get_session),
):
    if body.user_email.strip().lower() != user.email:
        raise HTTPException(status_code=403, detail="You can only offer help using your own account.")
    volunteer_skill = body.volunteer_skill.strip()
    if not volunteer_skill:
        raise HTTPException(status_code=400, detail="Please describe a volunteer skill.")
    need = session.get(BeneficiaryNeed, body.need_id)
    if (
        not need
        or not need.is_community_need
        or need.archived_at is not None
        or need.status in {NeedStatus.FULFILLED, NeedStatus.REJECTED}
    ):
        raise HTTPException(status_code=404, detail="Community need not found.")
    offer = VolunteerOffer(
        need_id=need.id,
        user_id=user.id,
        volunteer_skill=volunteer_skill,
        notes=body.notes.strip(),
    )
    session.add(offer)
    session.flush()
    add_record_history(
        session,
        request,
        "volunteer_offer",
        offer.id,
        "submitted",
        {"need_id": need.id},
    )
    session.commit()
    return {"success": True, "message": "Your offer to help has been submitted."}


class VolunteerSignupRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    full_name: str = Field(alias="fullName", min_length=1, max_length=200)
    phone: str = Field(default="", max_length=50)
    skills: str = Field(default="", max_length=500)
    location: str = Field(default="", max_length=200)
    availability: str = Field(default="Flexible", max_length=200)


class AssistanceRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    description: Optional[str] = Field(default=None, max_length=2000)
    request_details: Optional[str] = Field(
        default=None, alias="requestDetails", max_length=2000
    )
    location: Optional[str] = Field(default=None, max_length=200)
    area: Optional[str] = Field(default=None, max_length=200)
    contact_name: Optional[str] = Field(
        default=None, alias="contactName", max_length=200
    )
    contact_phone: str = Field(default="", alias="contactPhone", max_length=50)
    category: str = Field(min_length=1, max_length=200)
    urgency: str = Field(default="Medium", max_length=50)


@router.get("/auth/profile", response_model=ProfileUserResponse)
async def get_mobile_profile(user: User = Depends(require_mobile_user)):
    return {
        "userId": user.id,
        "fullName": user.full_name,
        "email": user.email,
        "role": "Volunteer",
        "phoneNumber": user.phone_number,
        "preferences": user.preferences,
    }


@router.put("/auth/profile", response_model=ProfileUserResponse)
async def update_profile(
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


@router.post(
    "/volunteers",
    dependencies=[Depends(_rate_limit("mobile-volunteer", 10, 3600))],
)
async def submit_volunteer(
    body: VolunteerSignupRequest,
    request: Request,
    user: User = Depends(require_mobile_user),
    session: Session = Depends(get_session),
):
    days = [d.strip() for d in body.availability.split(",") if d.strip()]
    volunteer = Volunteer(
        full_name=body.full_name.strip(),
        phone=body.phone.strip(),
        email=user.email,
        skills=body.skills.strip(),
        location=body.location.strip(),
        availability=body.availability.strip() or "Flexible / Not Specified",
        available_days=days,
        status=VolunteerStatus.ACTIVE,
    )
    session.add(volunteer)
    session.flush()
    add_record_history(
        session,
        request,
        "volunteer",
        volunteer.id,
        "submitted",
        {"source": "mobile", "onboarding_status": volunteer.onboarding_status},
    )
    session.commit()
    return {"success": True, "message": "Volunteer registration submitted."}


@router.post(
    "/assistance-requests",
    dependencies=[Depends(_rate_limit("mobile-assistance", 10, 3600))],
)
async def submit_assistance_request(
    body: AssistanceRequest,
    request: Request,
    user: User = Depends(require_mobile_user),
    session: Session = Depends(get_session),
):
    try:
        urgency = NeedUrgency(body.urgency.strip().capitalize())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid assistance urgency.") from exc
    category = body.category.strip()
    if not category:
        raise HTTPException(status_code=400, detail="Assistance category is required.")
    location = (body.location if body.location is not None else body.area or "").strip()
    description = (
        body.description
        if body.description is not None
        else body.request_details or ""
    ).strip()
    need = BeneficiaryNeed(
        user_id=user.id,
        contact_name=user.full_name,
        contact_phone=body.contact_phone.strip() or user.phone_number or "",
        full_address=location,
        anonymised_title=f"{category} assistance request",
        area=location,
        category=category,
        request_details=description,
        urgency=urgency,
        status=NeedStatus.PENDING,
    )
    session.add(need)
    session.flush()
    add_record_history(
        session,
        request,
        "beneficiary_need",
        need.id,
        "submitted",
        {"source": "mobile", "status": NeedStatus.PENDING.value},
    )
    session.commit()
    return {"success": True, "message": "Assistance request submitted.", "needId": need.id}


@router.post(
    "/donations",
    dependencies=[Depends(_rate_limit("mobile-donation", 5, 3600))],
    response_model=DonationResponse,
)
async def submit_donation(
    body: DonationRequest,
    request: Request,
    user: User = Depends(require_mobile_user),
    session: Session = Depends(get_session),
):
    if body.user_email and body.user_email.strip().lower() != user.email:
        raise HTTPException(status_code=403, detail="You can only donate using your own account.")
    donation_type = body.donation_type.strip().lower().replace("-", "").replace("_", "")
    if donation_type not in {"monetary", "inkind"}:
        raise HTTPException(status_code=400, detail="Invalid donation type.")
    category = (body.category or "").strip()
    item_category = (body.item_category or "").strip()
    item_description = (body.item_description or "").strip()

    amount = Decimal("0.00")
    if donation_type == "monetary":
        if body.amount is None:
            raise HTTPException(status_code=400, detail="Donation amount is required.")
        category = category or "General Fund (Where Most Needed)"
        try:
            amount = body.amount.quantize(Decimal("0.01"))
        except InvalidOperation as exc:
            raise HTTPException(status_code=400, detail="Invalid donation amount.") from exc
        if amount != body.amount or not amount.is_finite() or amount <= 0:
            raise HTTPException(status_code=400, detail="Donation amount must be positive and use at most two decimals.")
        payment_method = "Pledge - No Online Payment"
    else:
        if not item_category or not item_description:
            raise HTTPException(
                status_code=400,
                detail="Item category and description are required for in-kind donations.",
            )
        category = category or item_category
        logistics_type = (
            body.drop_off_option or body.logistics_type or "dropoff"
        ).strip().lower().replace("_", "")
        if logistics_type not in {"dropoff", "pickup"}:
            raise HTTPException(status_code=400, detail="Invalid in-kind drop-off option.")
        if logistics_type == "pickup" and not (body.pickup_address or "").strip():
            raise HTTPException(
                status_code=400,
                detail="A collection address is required for pickup.",
            )
        payment_method = "In-Kind Delivery"

    donation = Donation(
        donor_name=user.full_name,
        donor_email=user.email,
        cause=category,
        donation_type=donation_type,
        amount=amount,
        item_category=item_category or None,
        item_description=item_description or None,
        logistics_type=(
            logistics_type if donation_type == "inkind" else None
        ),
        pickup_address=(
            body.pickup_address.strip()
            if donation_type == "inkind"
            and logistics_type == "pickup"
            and body.pickup_address
            else None
        ),
        payment_method=payment_method,
        status=DonationStatus.SUBMITTED.value,
        is_verified=False,
    )
    session.add(donation)
    session.flush()
    add_record_history(
        session,
        request,
        "donation",
        donation.id,
        "submitted",
        {"source": "mobile", "status": donation.status},
    )
    session.commit()
    return {
        "success": True,
        "transactionRef": f"AC-{donation.id:06d}",
        "message": (
            "Your donation pledge has been recorded. No payment was processed."
            if donation_type == "monetary"
            else "Your in-kind donation offer has been recorded."
        ),
    }
