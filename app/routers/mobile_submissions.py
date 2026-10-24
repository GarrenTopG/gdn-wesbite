from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlmodel import Session

from app.assistance_validation import parse_need_urgency
from app.db.session import get_session
from app.models.entities import (
    BeneficiaryNeed,
    Donation,
    DonationStatus,
    NeedStatus,
    User,
    Volunteer,
    VolunteerStatus,
)
from app.routers.mobile_dependencies import _rate_limit, require_mobile_user
from app.schemas.mobile import (
    AssistanceRequest,
    DonationRequest,
    DonationResponse,
    VolunteerSignupRequest,
)
from app.security import add_record_history

router = APIRouter()


@router.post(
    "/volunteers",
    dependencies=[Depends(_rate_limit("mobile-volunteer", 10, 3600))],
)
def submit_volunteer(
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
def submit_assistance_request(
    body: AssistanceRequest,
    request: Request,
    user: User = Depends(require_mobile_user),
    session: Session = Depends(get_session),
):
    try:
        urgency = parse_need_urgency(body.urgency)
    except ValueError as exc:
        raise HTTPException(
            status_code=400, detail="Invalid assistance urgency."
        ) from exc
    category = body.category.strip()
    if not category:
        raise HTTPException(status_code=400, detail="Assistance category is required.")
    location = (body.location if body.location is not None else body.area or "").strip()
    description = (
        body.description if body.description is not None else body.request_details or ""
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
    return {
        "success": True,
        "message": "Assistance request submitted.",
        "needId": need.id,
    }


@router.post(
    "/donations",
    dependencies=[Depends(_rate_limit("mobile-donation", 5, 3600))],
    response_model=DonationResponse,
)
def submit_donation(
    body: DonationRequest,
    request: Request,
    user: User = Depends(require_mobile_user),
    session: Session = Depends(get_session),
):
    if body.user_email and body.user_email.strip().lower() != user.email:
        raise HTTPException(
            status_code=403, detail="You can only donate using your own account."
        )
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
            raise HTTPException(
                status_code=400, detail="Invalid donation amount."
            ) from exc
        if amount != body.amount or not amount.is_finite() or amount <= 0:
            raise HTTPException(
                status_code=400,
                detail="Donation amount must be positive and use at most two decimals.",
            )
        payment_method = "Pledge - No Online Payment"
    else:
        if not item_category or not item_description:
            raise HTTPException(
                status_code=400,
                detail="Item category and description are required for in-kind donations.",
            )
        category = category or item_category
        logistics_type = (
            (body.drop_off_option or body.logistics_type or "dropoff")
            .strip()
            .lower()
            .replace("_", "")
        )
        if logistics_type not in {"dropoff", "pickup"}:
            raise HTTPException(
                status_code=400, detail="Invalid in-kind drop-off option."
            )
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
        logistics_type=(logistics_type if donation_type == "inkind" else None),
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
