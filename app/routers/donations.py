from decimal import Decimal, InvalidOperation
from io import BytesIO
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse, StreamingResponse
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from sqlmodel import Session, select
from datetime import timezone
import hashlib
import secrets

from app.db.session import get_session
from app.models.entities import BeneficiaryNeed, Donation, NeedStatus, ReceiptAccess
from app.security import (
    add_record_history,
    enforce_receipt_rate_limit,
    enforce_public_form_rate_limit,
    now_utc,
    require_csrf,
)
from app.templatesconfig import templates

router = APIRouter(
    prefix="/donate",
    tags=["Donations"],
    dependencies=[
        Depends(require_csrf),
        Depends(enforce_public_form_rate_limit),
    ],
)
receipt_router = APIRouter(
    prefix="/donate",
    tags=["Donations"],
    dependencies=[
        Depends(require_csrf),
        Depends(enforce_receipt_rate_limit),
    ],
)

# Donation route to render the donation page
@router.get("", response_class=HTMLResponse)
async def get_donate_page(
    request: Request,
    need_id: Optional[int] = None,
    session: Session = Depends(get_session),
):
    active_needs = session.exec(
        select(BeneficiaryNeed).where(
            BeneficiaryNeed.is_community_need.is_(True),
            BeneficiaryNeed.status != NeedStatus.FULFILLED,
        )
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

# Donation route to handle donation form submission
@router.post("", response_class=HTMLResponse)
async def submit_donation_form(
    request: Request,
    session: Session = Depends(get_session),
):
    form_data = await request.form()

    donation_type = str(form_data.get("donation_type", "monetary")).strip()
    if donation_type not in {"monetary", "inkind"}:
        raise HTTPException(status_code=400, detail="Invalid donation type.")
    is_anon = form_data.get("is_anonymous") == "true"
    donor_name_raw = str(form_data.get("donor_name", "")).strip()
    donor_name = "Anonymous Donor" if (is_anon or not donor_name_raw) else donor_name_raw

    country_code = str(form_data.get("country_code", "+27")).strip()
    phone_str = str(form_data.get("phone", "")).strip()
    donor_phone = f"{country_code} {phone_str}" if phone_str else None
    
    # Clean email input: set to None if blank
    raw_email = str(form_data.get("donor_email", "")).strip()
    donor_email = raw_email if raw_email else None  # <-- UPDATED

    message_val = str(form_data.get("message", "")).strip() or None

    req_tax = form_data.get("request_tax_certificate") == "true"
    tax_id = str(form_data.get("tax_id_number", "")).strip() if req_tax else None
    tax_addr = str(form_data.get("tax_address", "")).strip() if req_tax else None
    if req_tax and donation_type != "monetary":
        raise HTTPException(
            status_code=400,
            detail="Tax receipts can only be requested for monetary donations.",
        )
    if req_tax and (
        is_anon
        or not donor_name_raw
        or not donor_email
        or not tax_id
        or not tax_addr
    ):
        raise HTTPException(
            status_code=400,
            detail="A receipt request requires your name, email, tax ID, and address.",
        )

    amount_val = Decimal("0.00")
    cause_val = None
    target_need_id = None

    if donation_type == "monetary":
        raw_amount = form_data.get("amount", "0")
        try:
            amount_val = Decimal(str(raw_amount))
        except (ValueError, InvalidOperation):
            raise HTTPException(status_code=400, detail="Invalid donation amount.")
        if not amount_val.is_finite() or amount_val <= Decimal("0.00"):
            raise HTTPException(status_code=400, detail="Donation amount must be positive.")
        try:
            rounded_amount = amount_val.quantize(Decimal("0.01"))
        except InvalidOperation as exc:
            raise HTTPException(status_code=400, detail="Invalid donation amount precision.") from exc
        if rounded_amount != amount_val:
            raise HTTPException(
                status_code=400,
                detail="Donation amounts may have at most two decimals.",
            )

        raw_need_id = form_data.get("need_id")
        cause_val = "General Fund (Where Most Needed)"

        if raw_need_id and isinstance(raw_need_id, str):
            cleaned_need_id = raw_need_id.strip()
            if cleaned_need_id.isdigit():
                target_need_id = int(cleaned_need_id)
                linked_need = session.get(BeneficiaryNeed, target_need_id)
                if (
                    not linked_need
                    or not linked_need.is_community_need
                    or linked_need.status == NeedStatus.FULFILLED
                ):
                    raise HTTPException(status_code=400, detail="Selected community need is unavailable.")
                cause_val = f"Targeted: {linked_need.anonymised_title}"

    # In-Kind Attributes
    item_category = str(form_data.get("item_category", "")).strip() if donation_type == "inkind" else None
    item_description = str(form_data.get("item_description", "")).strip() if donation_type == "inkind" else None
    logistics_type = str(form_data.get("logistics_type", "")).strip() if donation_type == "inkind" else None
    pickup_address = str(form_data.get("pickup_address", "")).strip() if logistics_type == "pickup" else None

    new_donation = Donation(
        donor_name=donor_name,
        donor_email=donor_email,
        donor_phone=donor_phone,
        donation_type=donation_type,
        amount=amount_val,
        cause=cause_val,
        need_id=target_need_id,
        item_category=item_category,
        item_description=item_description,
        logistics_type=logistics_type,
        pickup_address=pickup_address,
        request_tax_certificate=req_tax,
        tax_id_number=tax_id,
        tax_address=tax_addr,
        payment_method=(
            "Pledge - No Online Payment"
            if donation_type == "monetary"
            else "In-Kind Delivery"
        ),
        message=message_val,
        is_anonymous=is_anon,
        is_verified=False,
    )

    receipt_token = None
    if req_tax:
        receipt_token = secrets.token_urlsafe(32)
        new_donation.pending_receipt_token_hash = hashlib.sha256(
            receipt_token.encode("utf-8")
        ).hexdigest()
    session.add(new_donation)
    session.flush()
    add_record_history(
        session,
        request,
        "donation",
        new_donation.id,
        "submitted",
        {
            "status": new_donation.status,
            "tax_receipt_requested": req_tax,
        },
    )
    session.commit()
    session.refresh(new_donation)

    active_needs = session.exec(
        select(BeneficiaryNeed).where(
            BeneficiaryNeed.is_community_need.is_(True),
            BeneficiaryNeed.status != NeedStatus.FULFILLED,
        )
    ).all()

    return templates.TemplateResponse(
        request=request,
        name="donate.html",
        context={
            "active_page": "donate",
            "submitted": True,
            "receipt_token": receipt_token,
            "request_tax": req_tax,
            "amount": f"{amount_val:.2f}",
            "active_needs": active_needs,
        },
    )

# Donation route to download a tax certificate for a specific donation
@receipt_router.post("/tax-certificate", name="download_tax_certificate")
async def download_tax_certificate(
    request: Request,
    session: Session = Depends(get_session),
):
    form = await request.form()
    token = str(form.get("receipt_token", ""))
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    access = session.exec(
        select(ReceiptAccess).where(ReceiptAccess.token_hash == token_hash)
    ).first()
    if not access:
        pending_donation = session.exec(
            select(Donation).where(
                Donation.pending_receipt_token_hash == token_hash,
                Donation.request_tax_certificate.is_(True),
                Donation.is_verified.is_(False),
            )
        ).first()
        if pending_donation:
            return HTMLResponse(
                content=(
                    "The receipt is not available yet. Staff must first verify "
                    "that payment was received."
                ),
                status_code=status.HTTP_202_ACCEPTED,
                headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"},
            )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tax certificate not available for this record.",
        )
    expires_at = access.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at <= now_utc():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tax certificate not available for this record.",
        )
    donation = session.get(Donation, access.donation_id)
    if (
        not donation
        or not donation.request_tax_certificate
        or not donation.is_verified
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tax certificate not available for this record."
        )

    buffer = BytesIO()
    p = canvas.Canvas(buffer, pagesize=letter)
    
    # Document Header
    p.setFont("Helvetica-Bold", 18)
    p.drawString(100, 750, "SECTION 18A TAX DEDUCTION RECEIPT")
    p.setFont("Helvetica", 10)
    p.drawString(100, 735, "Aurorah Community Action Network (PBO / NPO)")
    p.line(100, 725, 500, 725)

    # Details Grid - All dynamic parameters explicitly wrapped as str()
    p.setFont("Helvetica-Bold", 12)
    issued_year = donation.created_at.year
    p.drawString(100, 690, f"Receipt Number: CAN-18A-{issued_year}-{str(donation.id)}")
    
    p.setFont("Helvetica", 11)
    p.drawString(100, 660, f"Donor Name: {str(donation.donor_name)}")
    p.drawString(100, 640, f"SARS Tax Ref / ID: {str(donation.tax_id_number or 'N/A')}")
    p.drawString(100, 620, f"Address: {str(donation.tax_address or 'N/A')}")
    
    # FIXED: Wrapped str(donation.id) instead of passing int directly
    p.drawString(100, 600, f"Transaction Ref ID: #{str(donation.id)}")
    
    p.setFont("Helvetica", 11)
    p.drawString(100, 580, f"Amount Received: R{donation.amount:.2f}")
    p.drawString(100, 560, f"Cause / Allocated Need: {str(donation.cause or 'General Fund')}")

    p.setFont("Helvetica-Oblique", 9)
    p.drawString(100, 500, "Issued in terms of Section 18A of the Income Tax Act No 58 of 1962.")
    p.drawString(100, 485, "The funds will be used exclusively for public benefit activities.")

    p.showPage()
    p.save()
    buffer.seek(0)

    return StreamingResponse(
        buffer,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="Section18A_Receipt_{donation.id}.pdf"',
            "Cache-Control": "no-store",
            "Referrer-Policy": "no-referrer",
        },
    )