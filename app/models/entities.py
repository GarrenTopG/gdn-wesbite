from datetime import datetime
from typing import Optional
from sqlmodel import Field, SQLModel


# --- USER & ADMIN AUTH ---
class User(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    full_name: str
    email: str = Field(unique=True, index=True)
    hashed_password: str
    role: str = Field(default="user")  # 'admin' or 'user'
    is_active: bool = Field(default=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)


# --- VOLUNTEER ENTITY ---
class Volunteer(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    full_name: str
    phone: str
    email: str
    skills: str  # Comma-separated (e.g., "Food Dist, Logistics, Medical")
    location: str  # Neighborhood / Suburb
    availability: str  # "Weekdays", "Weekends", "Anytime"
    status: str = Field(default="Active")  # 'Active', 'Inactive', 'Assigned'
    created_at: datetime = Field(default_factory=datetime.utcnow)


# --- BENEFICIARY & NEED ENTITY (POPIA Compliant) ---
class BeneficiaryNeed(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    # Private POPIA Restricted Data (Admin-only access)
    contact_name: str
    contact_phone: str
    full_address: str

    # Public-Facing Anonymised Data
    anonymised_title: str  # e.g. "Food relief needed for household of 4"
    area: str  # e.g. "Zone 3"
    category: str  # 'Food', 'Clothing', 'Shelter', 'Other'
    urgency: str  # 'Low', 'Medium', 'High', 'Critical'
    status: str = Field(
        default="Pending"
    )  # 'Pending', 'Matched', 'Fulfilled'
    created_at: datetime = Field(default_factory=datetime.utcnow)


# --- DONATION ENTITY ---
class Donation(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    donor_name: str
    donor_email: str
    amount: float
    payment_method: str  # 'Gateway', 'EFT Upload'
    proof_of_payment_url: Optional[str] = None  # Upload file path for EFTs
    is_verified: bool = Field(default=False)
    created_at: datetime = Field(default_factory=datetime.utcnow)


# --- MATCHING ENGINE ENTITY ---
class VolunteerMatch(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    need_id: int = Field(foreign_key="beneficiaryneed.id")
    volunteer_id: int = Field(foreign_key="volunteer.id")
    matched_by_admin: str = Field(default="System Scored")
    status: str = Field(default="Assigned")  # 'Assigned', 'Completed'
    matched_at: datetime = Field(default_factory=datetime.utcnow)


# --- NEWS FEED ENTITY ---
class NewsArticle(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    title: str
    category: str  # 'Announcement', 'Story', 'Impact'
    content: str
    published_by: str = Field(default="Latifah Jacobs")
    created_at: datetime = Field(default_factory=datetime.utcnow)