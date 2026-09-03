from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Optional, List
from sqlmodel import Field, SQLModel, Column, JSON


# --- ENUMS FOR CONSTRAINED VALUES ---
class UserRole(str, Enum):
    ADMIN = "admin"
    USER = "user"


class NeedUrgency(str, Enum):
    LOW = "Low"
    MEDIUM = "Medium"
    HIGH = "High"
    CRITICAL = "Critical"


class NeedStatus(str, Enum):
    PENDING = "Pending"
    IN_PROGRESS = "In Progress"
    MATCHED = "Matched"
    FULFILLED = "Fulfilled"
    REJECTED = "Rejected"


class VolunteerStatus(str, Enum):
    ACTIVE = "Active"
    INACTIVE = "Inactive"
    ASSIGNED = "Assigned"


# --- USER & ADMIN AUTH ---
class User(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    full_name: str
    email: str = Field(unique=True, index=True)
    hashed_password: str
    role: UserRole = Field(default=UserRole.USER)
    is_active: bool = Field(default=True)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


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
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


# --- BENEFICIARY & NEED ENTITY (POPIA Compliant) ---
class BeneficiaryNeed(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)

    # Restricted POPIA Personal Data (Admin/Internal Route Access Only)
    contact_name: str
    contact_phone: str
    full_address: str

    # Public Anonymised Data
    anonymised_title: str
    area: str
    category: str  # 'Food', 'Clothing', 'Shelter', 'Other'
    urgency: NeedUrgency = Field(default=NeedUrgency.MEDIUM)
    status: NeedStatus = Field(default=NeedStatus.PENDING, index=True)

    # Financial / Resource Metrics
    target_amount: Decimal = Field(default=Decimal("0.00"), max_digits=12, decimal_places=2)
    current_amount: Decimal = Field(default=Decimal("0.00"), max_digits=12, decimal_places=2)

    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


class Donation(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    donor_name: str
    donor_email: Optional[str] = Field(default=None, index=True)
    donor_phone: Optional[str] = None

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

    # Verification & Payment Tracking
    payment_method: str = Field(default="Gateway")
    proof_of_payment_url: Optional[str] = None
    message: Optional[str] = None
    is_anonymous: bool = Field(default=False)
    is_verified: bool = Field(default=False, index=True)

    need_id: Optional[int] = Field(
        default=None, foreign_key="beneficiaryneed.id", index=True
    )
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
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )