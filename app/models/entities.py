from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Optional, List
from sqlalchemy import UniqueConstraint
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
    REFUNDED = "Refunded"

class NewsStatus(str, Enum):
    DRAFT = "Draft"
    PREVIEW = "Preview"
    PUBLISHED = "Published"
    ARCHIVED = "Archive"

# ENUMS FOR VOLUNTEER STATUS
class VolunteerStatus(str, Enum):
    ACTIVE = "Active"
    INACTIVE = "Inactive"
    ASSIGNED = "Assigned"


# --- USER ENTITY ---
class User(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    full_name: str
    email: str = Field(unique=True, index=True)
    hashed_password: str
    role: UserRole = Field(default=UserRole.USER)
    is_active: bool = Field(default=True)
    mfa_secret: Optional[str] = Field(default=None)
    mfa_last_counter: Optional[int] = Field(default=None)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


class AuthSession(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    token_hash: str = Field(unique=True, index=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    expires_at: datetime = Field(index=True)
    mfa_verified: bool = Field(default=False, index=True)
    mfa_setup_secret: Optional[str] = Field(default=None)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class AuditLog(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    actor_id: Optional[int] = Field(default=None, foreign_key="user.id", index=True)
    actor_identity: str = Field(index=True)
    action: str = Field(index=True)
    target_type: str = Field(index=True)
    target_id: Optional[str] = Field(default=None, index=True)
    occurred_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc), index=True
    )
    details: Optional[str] = None


class ReceiptAccess(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    donation_id: int = Field(foreign_key="donation.id", index=True)
    token_hash: str = Field(unique=True, index=True)
    expires_at: datetime = Field(index=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class RateLimitHit(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    bucket_key: str = Field(index=True)
    occurred_at: int = Field(index=True)


# --- VOLUNTEER ENTITY ---
class Volunteer(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    full_name: str
    phone: str
    email: str = Field(index=True)
    skills: str  # Comma-separated (e.g., "Food Dist, Logistics, Medical")
    location: str  # Suburb / Area
    availability: str = Field(default="Anytime")  # e.g., "Weekdays", "Weekends", "Anytime"
    
    # Store specific days the volunteer indicated they are available for
    available_days: List[str] = Field(default_factory=list, sa_column=Column(JSON))  # e.g., ["Monday", "Wednesday", "Saturday"]
    assigned_day: Optional[str] = Field(default="Inactive")  # "Inactive" by default or chosen day
    
    status: VolunteerStatus = Field(default=VolunteerStatus.ACTIVE)
    onboarding_status: str = Field(default="Pending", index=True)
    next_assignment_at: Optional[datetime] = Field(default=None, index=True)
    archived_at: Optional[datetime] = Field(default=None, index=True)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


# --- BENEFICIARY & NEED ENTITY (POPIA Compliant) ---
class BeneficiaryNeed(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    is_community_need: bool = Field(default=False, index=True)

    # Restricted POPIA Personal Data (Admin/Internal Route Access Only)
    contact_name: str
    contact_phone: str
    full_address: str

    # Public Anonymised Data
    anonymised_title: str
    area: str
    category: str  # 'Food', 'Clothing', 'Shelter', 'Other'
    request_details: Optional[str] = None
    urgency: NeedUrgency = Field(default=NeedUrgency.MEDIUM)
    status: NeedStatus = Field(default=NeedStatus.PENDING, index=True)

    # Financial / Resource Metrics
    target_amount: Decimal = Field(default=Decimal("0.00"), max_digits=12, decimal_places=2)
    current_amount: Decimal = Field(default=Decimal("0.00"), max_digits=12, decimal_places=2)

    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    closed_at: Optional[datetime] = Field(default=None, index=True)
    assigned_staff_id: Optional[int] = Field(default=None, foreign_key="user.id", index=True)
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
    donor_email: Optional[str] = Field(default=None, index=True)
    donor_phone: Optional[str] = None

    cause: Optional[str] = Field(default="General Fund (Where Most Needed)")

    # Monetary vs In-Kind Classification
    donation_type: str = Field(default="monetary", index=True)  # 'monetary' or 'inkind'
    amount: Decimal = Field(default=Decimal("0.00"), max_digits=12, decimal_places=2)
    allocated_amount: Decimal = Field(default=Decimal("0.00"), max_digits=12, decimal_places=2)

    # In-Kind Physical Item Attributes
    item_category: Optional[str] = None
    item_description: Optional[str] = None
    logistics_type: Optional[str] = None
    pickup_address: Optional[str] = None

    # Section 18A Tax Certificate Attributes
    request_tax_certificate: bool = Field(default=False)
    tax_id_number: Optional[str] = None
    tax_address: Optional[str] = None
    pending_receipt_token_hash: Optional[str] = Field(default=None, index=True)

    # Verification & Payment Tracking
    payment_method: str = Field(default="Gateway")
    proof_of_payment_url: Optional[str] = None
    message: Optional[str] = None
    is_anonymous: bool = Field(default=False)
    is_verified: bool = Field(default=False, index=True)
    status: str = Field(default=DonationStatus.SUBMITTED.value, index=True)
    archived_at: Optional[datetime] = Field(default=None, index=True)

    need_id: Optional[int] = Field(
        default=None, foreign_key="beneficiaryneed.id", index=True
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


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
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


# --- MATCHING ENGINE ENTITY ---
class VolunteerMatch(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    need_id: int = Field(foreign_key="beneficiaryneed.id", index=True)
    volunteer_id: int = Field(foreign_key="volunteer.id", index=True)
    matched_by_admin: str = Field(default="System Scored")
    status: str = Field(default="Assigned")
    assigned_for: Optional[datetime] = Field(default=None, index=True)
    matched_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


# --- NEWS ARTICLE ENTITY ---
class NewsArticle(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    title: str
    slug: str = Field(index=True, unique=True)
    category: str = Field(default="Community")
    summary: str
    content: str
    image_url: Optional[str] = None
    author: str = Field(default="Aurorah Team")
    is_featured: bool = Field(default=False)
    status: str = Field(default=NewsStatus.DRAFT.value, index=True)
    archived_at: Optional[datetime] = Field(default=None, index=True)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


class RecordHistory(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    record_type: str = Field(index=True)
    record_id: int = Field(index=True)
    actor_id: Optional[int] = Field(default=None, foreign_key="user.id", index=True)
    action: str = Field(index=True)
    details: Optional[str] = None
    occurred_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc), index=True
    )