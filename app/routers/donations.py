from typing import Optional
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlmodel import Session, select

from app.db.session import get_session
from app.models.entities import BeneficiaryNeed, Donation
from app.templates_config import templates

router = APIRouter(prefix="/donate", tags=["Donations"])


@router.get("", response_class=HTMLResponse)
async def get_donate_page(
    request: Request,
    need_id: Optional[int] = None,
    session: Session = Depends(get_session),
):
    # Fetch active unfulfilled needs so donors can choose a specific cause
    active_needs = session.exec(
        select(BeneficiaryNeed).where(BeneficiaryNeed.status != "Fulfilled")
    ).all()

    return templates.TemplateResponse(
        request=request,
        name="donate.html",
        context={
            "active_page": "donate",
            "active_needs": active_needs,
            "selected_need_id": need_id,
        },
    )


@router.post("", response_class=HTMLResponse)
async def submit_donation_form(
    request: Request,
    session: Session = Depends(get_session),
):
    form_data = await request.form()

    # Safe Form Extraction with type guards
    is_anon = form_data.get("is_anonymous") == "true"

    donor_name_raw = form_data.get("donor_name")
    donor_name_str = str(donor_name_raw).strip() if isinstance(donor_name_raw, str) else ""
    donor_name = (
        "Anonymous Donor"
        if (is_anon or not donor_name_str)
        else donor_name_str
    )

    country_code_raw = form_data.get("country_code")
    country_code = str(country_code_raw).strip() if isinstance(country_code_raw, str) else "+27"
    
    phone_raw = form_data.get("phone")
    phone_str = str(phone_raw).strip() if isinstance(phone_raw, str) else ""
    donor_phone = f"{country_code} {phone_str}" if phone_str else None

    # Safe Float Conversion
    raw_amount = form_data.get("amount")
    amount_val = 0.0
    if isinstance(raw_amount, str):
        try:
            amount_val = float(raw_amount)
        except (ValueError, TypeError):
            amount_val = 0.0

   # Parse selected need ID or text cause from form
    raw_need_id = form_data.get("need_id")
    target_need_id: Optional[int] = None
    cause_val = "General Fund (Where Most Needed)"

    if raw_need_id and isinstance(raw_need_id, str):
        cleaned_need_id = raw_need_id.strip()
        
        # 1. If an integer ID was passed (Dynamic Database Need)
        if cleaned_need_id.isdigit():
            target_need_id = int(cleaned_need_id)
            linked_need = session.get(BeneficiaryNeed, target_need_id)
            if linked_need:
                cause_val = f"Targeted: {linked_need.anonymised_title}"
        
        # 2. If a text string was passed (e.g. "Food Parcels", "Educational Programs")
        elif cleaned_need_id:
            cause_val = cleaned_need_id

    donor_email_raw = form_data.get("donor_email")
    donor_email = str(donor_email_raw).strip() if isinstance(donor_email_raw, str) else ""

    message_raw = form_data.get("message")
    message_val = str(message_raw).strip() if isinstance(message_raw, str) and message_raw.strip() else None

    new_donation = Donation(
        donor_name=donor_name,
        donor_email=donor_email,
        donor_phone=donor_phone,
        amount=amount_val,
        cause=cause_val,
        need_id=target_need_id,
        payment_method="Gateway",
        message=message_val,
        is_anonymous=is_anon,
        is_verified=False,
    )

    session.add(new_donation)
    session.commit()
    session.refresh(new_donation)

    # Re-fetch active needs for response context
    active_needs = session.exec(
        select(BeneficiaryNeed).where(BeneficiaryNeed.status != "Fulfilled")
    ).all()

    return templates.TemplateResponse(
        request=request,
        name="donate.html",
        context={
            "active_page": "donate",
            "submitted": True,
            "amount": f"{amount_val:.2f}",
            "active_needs": active_needs,
        },
    )