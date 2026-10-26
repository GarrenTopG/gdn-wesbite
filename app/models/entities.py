from datetime import date, datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Optional, List
from sqlalchemy import Index, Text, UniqueConstraint
from sqlmodel import Field, SQLModel, Column, JSON


# ENUMS FOR CONSTRAINED VALUES
class UserRole(str, Enum):
    ADMINISTRATOR = "administrator"
    CASE_WORKER = "case_worker"
    FINANCE = "finance"
    CONTENT_EDITOR = "content_editor"
    READ_ONLY = "read_only"
    USER = "user"


# ENUMS FOR NEEDS AND VOLUNTEERS
class NeedUrgency(str, Enum):
    LOW = "Low"
    MEDIUM = "Medium"
    HIGH = "High"
    CRITICAL = "Critical"


# ENUMS FOR NEED STATUS AND VOLUNTEER STATUS
class NeedStatus(str, Enum):
    Open = "Open"
    PENDING = "Pending"
    IN_PROGRESS = "In Progress"
    MATCHED = "Matched"
    FULFILLED = "Fulfilled"
    REJECTED = "Rejected"


class DonationStatus(str, Enum):
    SUBMITTED = "Submitted"
    PAYMENT_PENDING = "Payment Pending"
    RECEIVED_VERIFIED = "Received/Verified"
    ALLOCATED = "Allocated"
    REJECTED = "Rejected"
    REFUNDED = "Refunded"


class NewsStatus(str, Enum):
    DRAFT = "Draft"
    PREVIEW = "Preview"
    PUBLISHED = "Published"
    ARCHIVED = "Archive"


class CampaignStatus(str, Enum):
    DRAFT = "Draft"
    PUBLISHED = "Published"
    PAUSED = "Paused"
    COMPLETED = "Completed"
    ARCHIVED = "Archived"


# ENUMS FOR VOLUNTEER STATUS
class VolunteerStatus(str, Enum):
    ACTIVE = "Active"
    INACTIVE = "Inactive"
    ASSIGNED = "Assigned"


# --- USER ENTITY ---
class User(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    full_name: str
    phone_number: Optional[str] = Field(default=None, max_length=50)
    preferences: Optional[dict[str, object]] = Field(
        default=None, sa_column=Column(JSON)
    )
    email: str = Field(max_length=255, unique=True, index=True)
    hashed_password: str
    role: UserRole = Field(default=UserRole.USER)
    is_active: bool = Field(default=True)
    mfa_secret: Optional[str] = Field(default=None)
    mfa_last_counter: Optional[int] = Field(default=None)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class AuthSession(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    token_hash: str = Field(max_length=255, unique=True, index=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    expires_at: datetime = Field(index=True)
    mfa_verified: bool = Field(default=False, index=True)
    mfa_setup_secret: Optional[str] = Field(default=None)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ExternalIdentity(SQLModel, table=True):
    __table_args__ = (UniqueConstraint("provider", "subject"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    provider: str = Field(max_length=30, index=True)
    subject: str = Field(max_length=255)
    email: str = Field(max_length=255)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class SsoTransaction(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    state_hash: str = Field(max_length=64, unique=True, index=True)
    provider: str = Field(max_length=30, index=True)
    client_type: str = Field(max_length=10)
    intent: str = Field(default="login", max_length=10)
    next_path: str = Field(default="/", max_length=2048)
    nonce: str = Field(max_length=128)
    provider_code_verifier: str = Field(max_length=128)
    mobile_code_challenge: Optional[str] = Field(default=None, max_length=128)
    link_user_id: Optional[int] = Field(default=None, foreign_key="user.id")
    expires_at: datetime = Field(index=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class MobileSsoCode(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    code_hash: str = Field(max_length=64, unique=True, index=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    code_challenge: str = Field(max_length=128)
    expires_at: datetime = Field(index=True)
    consumed_at: Optional[datetime] = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class StaffNotificationRead(SQLModel, table=True):
    __table_args__ = (UniqueConstraint("staff_user_id", "notification_key"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    staff_user_id: int = Field(foreign_key="user.id", index=True)
    notification_key: str = Field(max_length=255, index=True)
    fingerprint: str
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class AuditLog(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    actor_id: Optional[int] = Field(default=None, foreign_key="user.id", index=True)
    actor_identity: str = Field(max_length=255, index=True)
    action: str = Field(max_length=100, index=True)
    target_type: str = Field(max_length=100, index=True)
    target_id: Optional[str] = Field(default=None, max_length=100, index=True)
    occurred_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc), index=True
    )
    details: Optional[str] = None


class ReceiptAccess(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    donation_id: int = Field(foreign_key="donation.id", index=True)
    token_hash: str = Field(max_length=255, unique=True, index=True)
    expires_at: datetime = Field(index=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class RateLimitHit(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    bucket_key: str = Field(max_length=255, index=True)
    occurred_at: int = Field(index=True)


# --- VOLUNTEER ENTITY ---
class Volunteer(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    full_name: str
    phone: str
    email: str = Field(max_length=255, index=True)
    skills: str  # Comma-separated (e.g., "Food Dist, Logistics, Medical")
    location: str  # Suburb / Area
    availability: str = Field(
        default="Anytime"
    )  # e.g., "Weekdays", "Weekends", "Anytime"

    # Store specific days the volunteer indicated they are available for
    available_days: List[str] = Field(
        default_factory=list, sa_column=Column(JSON)
    )  # e.g., ["Monday", "Wednesday", "Saturday"]
    assigned_day: Optional[str] = Field(
        default="Inactive"
    )  # "Inactive" by default or chosen day

    status: VolunteerStatus = Field(default=VolunteerStatus.ACTIVE)
    onboarding_status: str = Field(default="Pending", max_length=50, index=True)
    next_assignment_at: Optional[datetime] = Field(default=None, index=True)
    archived_at: Optional[datetime] = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# --- BENEFICIARY & NEED ENTITY (POPIA Compliant) ---
class BeneficiaryNeed(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    is_community_need: bool = Field(default=False, index=True)
    user_id: Optional[int] = Field(default=None, foreign_key="user.id", index=True)

    # Restricted POPIA Personal Data (Admin/Internal Route Access Only)
    contact_name: str
    contact_phone: str
    full_address: str

    # Public Anonymised Data
    anonymised_title: str
    area: str
    category: str  # 'Food', 'Clothing', 'Shelter', 'Other'
    request_details: Optional[str] = None
    article: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    image_url: Optional[str] = Field(default=None, max_length=2048)
    image_alt: Optional[str] = Field(default=None, max_length=500)
    urgency: NeedUrgency = Field(default=NeedUrgency.MEDIUM)
    status: NeedStatus = Field(default=NeedStatus.PENDING, index=True)

    # Financial / Resource Metrics
    target_amount: Decimal = Field(
        default=Decimal("0.00"), max_digits=12, decimal_places=2
    )
    current_amount: Decimal = Field(
        default=Decimal("0.00"), max_digits=12, decimal_places=2
    )

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    closed_at: Optional[datetime] = Field(default=None, index=True)
    assigned_staff_id: Optional[int] = Field(
        default=None, foreign_key="user.id", index=True
    )
    internal_notes: Optional[str] = None
    follow_up_at: Optional[datetime] = Field(default=None, index=True)
    deadline: Optional[datetime] = Field(default=None, index=True)
    archived_at: Optional[datetime] = Field(default=None, index=True)


def set_need_status(need: BeneficiaryNeed, status: NeedStatus) -> None:
    terminal_statuses = {NeedStatus.FULFILLED, NeedStatus.REJECTED}
    if status in terminal_statuses and need.status not in terminal_statuses:
        need.closed_at = datetime.now(timezone.utc)
    elif status not in terminal_statuses:
        need.closed_at = None
    need.status = status


# --- DONATION ENTITY ---
class Donation(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    donor_name: str
    donor_email: Optional[str] = Field(default=None, max_length=255, index=True)
    donor_phone: Optional[str] = None

    cause: Optional[str] = Field(default="General Fund (Where Most Needed)")

    # Monetary vs In-Kind Classification
    donation_type: str = Field(
        default="monetary", max_length=50, index=True
    )  # 'monetary' or 'inkind'
    amount: Decimal = Field(default=Decimal("0.00"), max_digits=12, decimal_places=2)
    allocated_amount: Decimal = Field(
        default=Decimal("0.00"), max_digits=12, decimal_places=2
    )

    # In-Kind Physical Item Attributes
    item_category: Optional[str] = None
    item_description: Optional[str] = None
    logistics_type: Optional[str] = None
    pickup_address: Optional[str] = None

    # Section 18A Tax Certificate Attributes
    request_tax_certificate: bool = Field(default=False)
    tax_id_number: Optional[str] = None
    tax_address: Optional[str] = None
    pending_receipt_token_hash: Optional[str] = Field(
        default=None, max_length=255, index=True
    )

    # Verification & Payment Tracking
    payment_method: str = Field(default="Gateway")
    proof_of_payment_url: Optional[str] = None
    message: Optional[str] = None
    is_anonymous: bool = Field(default=False)
    is_verified: bool = Field(default=False, index=True)
    status: str = Field(
        default=DonationStatus.SUBMITTED.value, max_length=50, index=True
    )
    archived_at: Optional[datetime] = Field(default=None, index=True)

    need_id: Optional[int] = Field(
        default=None, foreign_key="beneficiaryneed.id", index=True
    )
    campaign_id: Optional[int] = Field(
        default=None, foreign_key="campaign.id", index=True
    )
    user_id: Optional[int] = Field(default=None, foreign_key="user.id", index=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class Campaign(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    title: str = Field(max_length=255)
    slug: str = Field(max_length=255, unique=True, index=True)
    summary: str
    story: str
    image_url: Optional[str] = Field(default=None, max_length=2048)
    image_alt: Optional[str] = Field(default=None, max_length=500)
    area: str = Field(max_length=255)
    category: str = Field(max_length=100)
    target_amount: Decimal = Field(max_digits=12, decimal_places=2)
    legacy_raised_amount: Decimal = Field(
        default=Decimal("0.00"), max_digits=12, decimal_places=2
    )
    status: CampaignStatus = Field(
        default=CampaignStatus.DRAFT, max_length=50, index=True
    )
    completion_return_status: Optional[str] = Field(default=None, max_length=50)
    deadline: Optional[date] = Field(default=None, index=True)
    created_by: Optional[int] = Field(default=None, foreign_key="user.id", index=True)
    legacy_need_id: Optional[int] = Field(
        default=None,
        foreign_key="beneficiaryneed.id",
        index=True,
    )
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    published_at: Optional[datetime] = Field(default=None, index=True)
    completed_at: Optional[datetime] = Field(default=None, index=True)
    archived_at: Optional[datetime] = Field(default=None, index=True)


class UserNotification(SQLModel, table=True):
    __table_args__ = (
        Index("ix_usernotification_user_created", "user_id", "created_at"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    donation_id: Optional[int] = Field(
        default=None, foreign_key="donation.id", index=True
    )
    campaign_id: Optional[int] = Field(
        default=None, foreign_key="campaign.id", index=True
    )
    event_type: str = Field(max_length=50, index=True)
    message: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    read_at: Optional[datetime] = Field(default=None, index=True)


class DonationAllocation(SQLModel, table=True):
    __table_args__ = (
        UniqueConstraint(
            "donation_id", "need_id", name="uq_donationallocation_donation_need"
        ),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    donation_id: int = Field(foreign_key="donation.id", index=True)
    need_id: int = Field(foreign_key="beneficiaryneed.id", index=True)
    amount: Decimal = Field(max_digits=12, decimal_places=2)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# --- MATCHING ENGINE ENTITY ---
class VolunteerMatch(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    need_id: int = Field(foreign_key="beneficiaryneed.id", index=True)
    volunteer_id: int = Field(foreign_key="volunteer.id", index=True)
    matched_by_admin: str = Field(default="System Scored")
    status: str = Field(default="Assigned")
    assigned_for: Optional[datetime] = Field(default=None, index=True)
    matched_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class VolunteerOffer(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    need_id: int = Field(foreign_key="beneficiaryneed.id", index=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    volunteer_skill: str
    notes: str = Field(default="")
    status: str = Field(default="Pending", max_length=50, index=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# --- NEWS ARTICLE ENTITY ---
class NewsArticle(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    title: str
    slug: str = Field(max_length=255, index=True, unique=True)
    category: str = Field(default="Community")
    summary: str
    content: str
    image_url: Optional[str] = None
    author: str = Field(default="Aurorah Team")
    is_featured: bool = Field(default=False)
    published_date: Optional[date] = Field(default=None)
    status: str = Field(default=NewsStatus.DRAFT.value, max_length=50, index=True)
    archived_at: Optional[datetime] = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class RecordHistory(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    record_type: str = Field(max_length=100, index=True)
    record_id: int = Field(index=True)
    actor_id: Optional[int] = Field(default=None, foreign_key="user.id", index=True)
    action: str = Field(max_length=100, index=True)
    details: Optional[str] = None
    occurred_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc), index=True
    )
