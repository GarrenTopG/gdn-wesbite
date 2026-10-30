from decimal import Decimal, InvalidOperation
from datetime import datetime, time, timezone
from io import BytesIO
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse, StreamingResponse
from sqlalchemy import false, true
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from sqlmodel import Session, select
from starlette.datastructures import FormData
import hashlib
import secrets

from app.db.session import get_session
from app.routers.form_data import parse_form_data
from app.routers.accounts import get_public_user
from app.services.donations import create_donation_with_history
from app.models.entities import (
    BeneficiaryNeed,
    Campaign,
    CampaignStatus,
    Donation,
    DonationStatus,
    NeedStatus,
    ReceiptAccess,
    UserNotification,
)
from app.security import (
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
community_needs_router = APIRouter(
    prefix="/community-needs",
    tags=["Community Needs"],
)
receipt_router = APIRouter(
    prefix="/donate",
    tags=["Donations"],
    dependencies=[
        Depends(require_csrf),
        Depends(enforce_receipt_rate_limit),
    ],
)
SUPPORT_AREAS = {
    "food_relief": "Food relief",
    "youth_learning": "Youth and learning",
    "community_library": "Community library",
    "community_development": "Community development",
}


def _public_campaigns_statement():
    return (
        select(Campaign)
        .where(
            Campaign.archived_at.is_(None),
            Campaign.status.in_(
                (
                    CampaignStatus.PUBLISHED,
                    CampaignStatus.PAUSED,
                    CampaignStatus.COMPLETED,
                )
            ),
        )
        .order_by(Campaign.created_at.desc())
    )


def _public_community_needs_statement(need_id: int | None = None):
    return _community_needs_statement(need_id=need_id, active_only=True)


def _community_needs_statement(
    *, need_id: int | None = None, active_only: bool
):
    statement = (
        select(
            BeneficiaryNeed.id,
            BeneficiaryNeed.anonymised_title,
            BeneficiaryNeed.area,
            BeneficiaryNeed.category,
            BeneficiaryNeed.urgency,
            BeneficiaryNeed.status,
            BeneficiaryNeed.target_amount,
            BeneficiaryNeed.current_amount,
            BeneficiaryNeed.article,
            BeneficiaryNeed.image_url,
            BeneficiaryNeed.image_alt,
            BeneficiaryNeed.deadline,
            BeneficiaryNeed.is_community_need,
            BeneficiaryNeed.archived_at,
            BeneficiaryNeed.request_details,
            BeneficiaryNeed.created_at,
        )
        .where(
            BeneficiaryNeed.is_community_need == true(),
            BeneficiaryNeed.status != NeedStatus.REJECTED,
            BeneficiaryNeed.archived_at.is_(None),
        )
        .order_by(BeneficiaryNeed.created_at.desc())
    )
    if active_only:
        start_of_today = datetime.combine(
            now_utc().date(), time.min, tzinfo=timezone.utc
        )
        statement = statement.where(
            (BeneficiaryNeed.deadline.is_(None))
            | (BeneficiaryNeed.deadline >= start_of_today)
        )
    if need_id is not None:
        statement = statement.where(BeneficiaryNeed.id == need_id)
    return statement


def _community_need_is_open(need: BeneficiaryNeed | dict) -> bool:
    get_value = need.get if isinstance(need, dict) else lambda key: getattr(need, key)
    deadline = get_value("deadline")
    if (
        not get_value("is_community_need")
        or get_value("archived_at") is not None
        or get_value("status") == NeedStatus.REJECTED
    ):
        return False
    if deadline is None:
        return True
    start_of_today = datetime.combine(now_utc().date(), time.min, tzinfo=timezone.utc)
    if deadline.tzinfo is None:
        deadline = deadline.replace(tzinfo=timezone.utc)
    return deadline >= start_of_today


def _community_need_excerpt(article: str | None, limit: int = 180) -> str:
    if not article or len(article) <= limit:
        return article or ""

    excerpt = article[: limit - 1]
    word_boundary = max(
        excerpt.rfind(" "),
        excerpt.rfind("\n"),
        excerpt.rfind("\t"),
    )
    if word_boundary > 0:
        excerpt = excerpt[:word_boundary]
    return f"{excerpt.rstrip()}…"


@community_needs_router.get("/{need_id}", response_class=HTMLResponse)
def community_need_detail(
    request: Request,
    need_id: int,
    session: Session = Depends(get_session),
):
    row = session.exec(
        _community_needs_statement(need_id=need_id, active_only=False)
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Community need not found.")

    need = dict(row._mapping)
    return templates.TemplateResponse(
        request=request,
        name="communityneeddetail.html",
        context={
            "active_page": "donate",
            "need": need,
            "need_is_open": _community_need_is_open(need),
        },
        headers={"Cache-Control": "no-store"},
    )


# Donation route to render the donation page
@router.get("", response_class=HTMLResponse)
def get_donate_page(
    request: Request,
    need_id: int | None = None,
    session: Session = Depends(get_session),
):
    community_needs = [
        {
            **dict(row._mapping),
            "article_excerpt": _community_need_excerpt(row.article),
        }
        for row in session.exec(_public_community_needs_statement()).all()
    ]
    available_need_ids = {str(need["id"]) for need in community_needs}
    selected_need_id = (
        str(need_id)
        if need_id is not None and str(need_id) in available_need_ids
        else None
    )
    return templates.TemplateResponse(
        request=request,
        name="donate.html",
        context={
            "active_page": "donate",
            "community_needs": community_needs,
            "selected_need_id": selected_need_id,
        },
    )


# Donation route to handle donation form submission
@router.post("", response_class=HTMLResponse)
def submit_donation_form(
    request: Request,
    form_data: FormData = Depends(parse_form_data),
    session: Session = Depends(get_session),
):
    request.state.donation_community_needs = [
        {
            **dict(row._mapping),
            "article_excerpt": _community_need_excerpt(row.article),
        }
        for row in session.exec(_public_community_needs_statement()).all()
    ]
    request.state.donation_form_values = {
        key: str(form_data.get(key, "")).strip()
        for key in (
            "donation_type",
            "amount",
            "request_tax_certificate",
            "tax_id_number",
            "tax_address",
            "need_id",
            "item_category",
            "item_description",
            "logistics_type",
            "pickup_address",
            "is_anonymous",
            "donor_name",
            "donor_email",
            "country_code",
            "phone",
            "message",
            "popia",
        )
    }

    donation_type = str(form_data.get("donation_type", "monetary")).strip()
    if donation_type not in {"monetary", "inkind"}:
        raise HTTPException(status_code=400, detail="Invalid donation type.")
    is_anon = form_data.get("is_anonymous") == "true"
    donor_name_raw = str(form_data.get("donor_name", "")).strip()
    donor_name = (
        "Anonymous Donor" if (is_anon or not donor_name_raw) else donor_name_raw
    )

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
        is_anon or not donor_name_raw or not donor_email or not tax_id or not tax_addr
    ):
        raise HTTPException(
            status_code=400,
            detail="A receipt request requires your name, email, tax ID, and address.",
        )

    amount_val = Decimal("0.00")
    cause_val = None
    selected_need = None

    if donation_type == "monetary":
        raw_amount = form_data.get("amount", "0")
        try:
            amount_val = Decimal(str(raw_amount))
        except (ValueError, InvalidOperation):
            raise HTTPException(status_code=400, detail="Invalid donation amount.")
        if not amount_val.is_finite() or amount_val <= Decimal("0.00"):
            raise HTTPException(
                status_code=400, detail="Donation amount must be positive."
            )
        try:
            rounded_amount = amount_val.quantize(Decimal("0.01"))
        except InvalidOperation as exc:
            raise HTTPException(
                status_code=400, detail="Invalid donation amount precision."
            ) from exc
        if rounded_amount != amount_val:
            raise HTTPException(
                status_code=400,
                detail="Donation amounts may have at most two decimals.",
            )

        raw_need_id = form_data.get("need_id")
        cause_val = "General Fund (Where Most Needed)"

        if raw_need_id and isinstance(raw_need_id, str):
            cleaned_need_id = raw_need_id.strip()
            if cleaned_need_id in SUPPORT_AREAS:
                cause_val = SUPPORT_AREAS[cleaned_need_id]
            else:
                try:
                    parsed_need_id = int(cleaned_need_id)
                except ValueError:
                    raise HTTPException(
                        status_code=400,
                        detail="Choose a valid community need.",
                    ) from None
                selected_need = session.get(BeneficiaryNeed, parsed_need_id)
                if not selected_need or not _community_need_is_open(selected_need):
                    raise HTTPException(
                        status_code=400,
                        detail="That community need is no longer accepting pledges.",
                    )
                cause_val = f"Community need: {selected_need.anonymised_title}"

    # In-Kind Attributes
    item_category = (
        str(form_data.get("item_category", "")).strip()
        if donation_type == "inkind"
        else None
    )
    item_description = (
        str(form_data.get("item_description", "")).strip()
        if donation_type == "inkind"
        else None
    )
    logistics_type = (
        str(form_data.get("logistics_type", "")).strip()
        if donation_type == "inkind"
        else None
    )
    pickup_address = (
        str(form_data.get("pickup_address", "")).strip()
        if logistics_type == "pickup"
        else None
    )

    donor = get_public_user(request, session)
    new_donation = Donation(
        donor_name=donor_name,
        donor_email=donor_email,
        donor_phone=donor_phone,
        donation_type=donation_type,
        amount=amount_val,
        cause=cause_val,
        need_id=selected_need.id if selected_need is not None else None,
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
        status=(
            DonationStatus.PAYMENT_PENDING.value
            if selected_need is not None
            else DonationStatus.SUBMITTED.value
        ),
        user_id=donor.id if donor else None,
    )

    receipt_token = None
    if req_tax:
        receipt_token = secrets.token_urlsafe(32)
        new_donation.pending_receipt_token_hash = hashlib.sha256(
            receipt_token.encode("utf-8")
        ).hexdigest()
    create_donation_with_history(
        session,
        request,
        new_donation,
        tax_receipt_requested=req_tax,
    )
    if (
        selected_need is not None
        and new_donation.user_id is not None
        and new_donation.id is not None
    ):
        session.add(
            UserNotification(
                user_id=new_donation.user_id,
                donation_id=new_donation.id,
                event_type="need_pledge_pending",
                message=(
                    f"Your pledge of R{amount_val:.2f} for "
                    f"{selected_need.anonymised_title} is pending admin review. "
                    "It is not included in the community total yet."
                ),
            )
        )
    session.commit()
    session.refresh(new_donation)

    return templates.TemplateResponse(
        request=request,
        name="donate.html",
        context={
            "active_page": "donate",
            "submitted": True,
            "receipt_token": receipt_token,
            "request_tax": req_tax,
            "amount": f"{amount_val:.2f}",
            "community_needs": request.state.donation_community_needs,
            "selected_need_id": str(selected_need.id)
            if selected_need is not None
            else None,
            "selected_need_title": (
                selected_need.anonymised_title if selected_need is not None else None
            ),
        },
    )


# Donation route to download a tax certificate for a specific donation
@receipt_router.post("/tax-certificate", name="download_tax_certificate")
def download_tax_certificate(
    request: Request,
    form: FormData = Depends(parse_form_data),
    session: Session = Depends(get_session),
):
    token = str(form.get("receipt_token", ""))
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    access = session.exec(
        select(ReceiptAccess).where(ReceiptAccess.token_hash == token_hash)
    ).first()
    if not access:
        pending_donation = session.exec(
            select(Donation).where(
                Donation.pending_receipt_token_hash == token_hash,
                Donation.request_tax_certificate == true(),
                Donation.is_verified == false(),
            )
        ).first()
        if pending_donation:
            if pending_donation.payment_method == "Pledge - No Online Payment":
                donation = pending_donation
            else:
                return templates.TemplateResponse(
                    request=request,
                    name="receipt_pending.html",
                    context={"active_page": "donate"},
                    status_code=status.HTTP_202_ACCEPTED,
                    headers={
                        "Cache-Control": "no-store",
                        "Referrer-Policy": "no-referrer",
                    },
                )
        else:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Tax certificate not available for this record.",
            )
    else:
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
                detail="Tax certificate not available for this record.",
            )

    buffer = BytesIO()
    p = canvas.Canvas(buffer, pagesize=letter, pageCompression=0)
    is_demo_receipt = donation.payment_method == "Pledge - No Online Payment"

    # Document Header
    p.setFont("Helvetica-Bold", 18)
    title = (
        "SECTION 18A DONATION CERTIFICATE"
        if is_demo_receipt
        else "SECTION 18A TAX DEDUCTION RECEIPT"
    )
    p.drawString(100, 750, title)
    p.setFont("Helvetica", 10)
    organization_name = "Aurorah Community Action Network"
    p.drawString(100, 735, organization_name)
    p.line(100, 725, 500, 725)

    details_y = 690
    if is_demo_receipt:
        p.setFillColorRGB(0.91, 0.78, 0.35)
        p.rect(100, 687, 400, 22, fill=1, stroke=0)
        p.setFillColorRGB(0, 0, 0)
        p.setFont("Helvetica-Bold", 10)
        p.drawCentredString(300, 694, "PLEDGE RECORD - PAYMENT NOT YET RECEIVED")
        p.setFillColorRGB(0, 0, 0)
        details_y = 660

    if is_demo_receipt:
        p.setFont("Helvetica-Bold", 12)
        p.setFillColorRGB(0.75, 0.0, 0.0)
        p.drawString(100, 610, "DEMO ONLY - NOT VALID FOR TAX PURPOSES")
        p.setFillColorRGB(0, 0, 0)
        p.setFont("Helvetica", 10)
        p.drawString(100, 595, "No payment was processed or received.")

    # Details Grid - All dynamic parameters explicitly wrapped as str()
    p.setFont("Helvetica-Bold", 12)
    issued_year = donation.created_at.year
    p.drawString(
        100, details_y, f"Receipt Number: CAN-18A-{issued_year}-{str(donation.id)}"
    )

    p.setFont("Helvetica", 11)
    p.drawString(100, details_y - 30, f"Donor Name: {str(donation.donor_name)}")
    p.drawString(
        100,
        details_y - 50,
        f"SARS Tax Ref / ID: {str(donation.tax_id_number or 'N/A')}",
    )
    p.drawString(100, details_y - 70, f"Address: {str(donation.tax_address or 'N/A')}")

    p.drawString(100, details_y - 90, f"Transaction Ref ID: #{str(donation.id)}")

    p.setFont("Helvetica", 11)
    amount_label = (
        "Pledge Amount (not received)" if is_demo_receipt else "Amount Received"
    )
    p.drawString(100, details_y - 110, f"{amount_label}: R{donation.amount:.2f}")
    p.drawString(
        100,
        details_y - 130,
        f"Cause / Allocated Need: {str(donation.cause or 'General Fund')}",
    )

    p.setFont("Helvetica-Oblique", 9)
    if is_demo_receipt:
        p.drawString(
            100,
            details_y - 170,
            "This certificate reflects the pledged donation recorded for the donor.",
        )
        p.drawString(
            100,
            details_y - 185,
            "Payment has not yet been processed or received and may still require verification.",
        )
    else:
        p.drawString(
            100,
            500,
            "Issued in terms of Section 18A of the Income Tax Act No 58 of 1962.",
        )
        p.drawString(
            100,
            485,
            "The funds will be used exclusively for public benefit activities.",
        )

    p.showPage()
    p.save()
    buffer.seek(0)

    filename = (
        f"DEMO_Section18A_Receipt_{donation.id}.pdf"
        if is_demo_receipt
        else f"Section18A_Receipt_{donation.id}.pdf"
    )
    return StreamingResponse(
        buffer,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
            "Referrer-Policy": "no-referrer",
        },
    )
