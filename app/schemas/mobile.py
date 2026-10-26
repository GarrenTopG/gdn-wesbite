from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


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
    content: str
    image_url: Optional[str] = None
    timestamp: str
    category: str


class NeedResponse(BaseModel):
    need_id: int = Field(alias="needId")
    title: str
    description: Optional[str] = ""
    location: str
    priority: str
    category: str
    status: str
    created_at: Optional[str] = Field(default=None, alias="createdAt")
    target_amount: Optional[Decimal] = Field(default=None, alias="targetAmount")
    current_amount: Optional[Decimal] = Field(default=None, alias="currentAmount")
    image_url: Optional[str] = Field(default=None, alias="imageUrl")
    image_alt: Optional[str] = Field(default=None, alias="imageAlt")
    article: Optional[str] = None
    article_excerpt: Optional[str] = Field(default=None, alias="articleExcerpt")
    deadline: Optional[str] = None

    model_config = ConfigDict(populate_by_name=True)


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
