from datetime import date
from decimal import Decimal, InvalidOperation
from types import SimpleNamespace
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlmodel import Session, select

from app.db.session import get_session
from app.models.entities import (
    Campaign,
    CampaignStatus,
    Donation,
    DonationStatus,
)
from app.routers.accounts import get_public_user
from app.security import (
    add_record_history,
    enforce_public_form_rate_limit,
    require_csrf,
)
from app.services.campaigns import campaign_raised_amount, notify_user
from app.templatesconfig import templates

router = APIRouter(prefix="/campaigns", tags=["Campaigns"])


def campaign_is_open(campaign: Campaign, today: date | None = None) -> bool:
    today = today or date.today()
    return (
        campaign.status == CampaignStatus.PUBLISHED
        and campaign.archived_at is None
        and (campaign.deadline is None or campaign.deadline >= today)
    )


def _public_campaign(session: Session, slug: str) -> Campaign:
    campaign = session.exec(
        select(Campaign).where(
            Campaign.slug == slug,
            Campaign.archived_at.is_(None),
            Campaign.status.in_(
                (
                    CampaignStatus.PUBLISHED,
                    CampaignStatus.PAUSED,
                    CampaignStatus.COMPLETED,
                )
            ),
        )
    ).first()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found.")
    return campaign


@router.get("/{slug}", response_class=HTMLResponse)
def campaign_detail(
    request: Request,
    slug: str,
    session: Session = Depends(get_session),
):
    campaign = _public_campaign(session, slug)
    raised = campaign_raised_amount(session, campaign)
    target = campaign.target_amount
    progress = min((raised / target * Decimal("100")) if target else Decimal(0), 100)
    return templates.TemplateResponse(
        request=request,
        name="campaigndetail.html",
        context={
            "active_page": "donate",
            "campaign": campaign,
            "raised": raised,
            "progress": progress,
            "campaign_is_open": campaign_is_open(campaign) and raised < target,
            "public_user": request.state.public_user,
        },
        headers={"Cache-Control": "no-store"},
    )


@router.post(
    "/{slug}/contribute",
    dependencies=[
        Depends(require_csrf),
        Depends(enforce_public_form_rate_limit),
    ],
)
def submit_simulated_contribution(
    request: Request,
    slug: str,
    amount: str = Form(...),
    is_anonymous: str | None = Form(None),
    demo_consent: str | None = Form(None),
    session: Session = Depends(get_session),
):
    next_path = f"/campaigns/{quote(slug, safe='')}"
    campaign = _public_campaign(session, slug)
    raised = campaign_raised_amount(session, campaign)
    target = campaign.target_amount
    request.state.campaign_submission = {
        "campaign": SimpleNamespace(
            id=campaign.id,
            title=campaign.title,
            slug=campaign.slug,
            summary=campaign.summary,
            story=campaign.story,
            image_url=campaign.image_url,
            image_alt=campaign.image_alt,
            area=campaign.area,
            category=campaign.category,
            target_amount=campaign.target_amount,
            status=campaign.status,
            deadline=campaign.deadline,
            archived_at=campaign.archived_at,
        ),
        "raised": raised,
        "progress": min(
            (raised / target * Decimal("100")) if target else Decimal(0), 100
        ),
        "campaign_is_open": campaign_is_open(campaign) and raised < target,
        "contribution_amount": amount,
    }
    user = get_public_user(request, session)
    if not user:
        return RedirectResponse(
            f"/account/login?next_path={quote(next_path, safe='')}",
            status_code=303,
        )

    if campaign.id is None or user.id is None:
        raise HTTPException(status_code=409, detail="Could not link this contribution.")
    if not campaign_is_open(campaign) or raised >= target:
        raise HTTPException(
            status_code=409,
            detail="This campaign is not currently accepting contributions.",
        )
    if demo_consent != "true":
        raise HTTPException(
            status_code=400,
            detail="Confirm that you understand this is a simulated contribution.",
        )
    try:
        parsed_amount = Decimal(amount.strip())
    except (InvalidOperation, ValueError):
        raise HTTPException(status_code=400, detail="Enter a valid amount.") from None
    if (
        not parsed_amount.is_finite()
        or parsed_amount < Decimal("10.00")
        or parsed_amount > Decimal("9999999999.99")
    ):
        raise HTTPException(
            status_code=400,
            detail="Enter an amount between R10.00 and R9,999,999,999.99.",
        )
    try:
        rounded_amount = parsed_amount.quantize(Decimal("0.01"))
    except InvalidOperation as exc:
        raise HTTPException(
            status_code=400, detail="Invalid amount precision."
        ) from exc
    if rounded_amount != parsed_amount:
        raise HTTPException(
            status_code=400, detail="Amounts may have at most two decimal places."
        )

    anonymous = is_anonymous == "true"
    donation = Donation(
        donor_name="Anonymous Donor" if anonymous else user.full_name,
        donor_email=user.email,
        donation_type="monetary",
        amount=parsed_amount,
        cause=f"Campaign: {campaign.title}",
        payment_method="Simulated Contribution - No Payment",
        message=None,
        is_anonymous=anonymous,
        is_verified=False,
        status=DonationStatus.PAYMENT_PENDING.value,
        campaign_id=campaign.id,
        user_id=user.id,
    )
    session.add(donation)
    session.flush()
    add_record_history(
        session,
        request,
        "donation",
        donation.id,
        "simulated_campaign_contribution_submitted",
        {"campaign_id": campaign.id, "amount": str(parsed_amount)},
    )
    notify_user(
        session,
        user_id=user.id,
        campaign_id=campaign.id,
        donation_id=donation.id,
        event_type="contribution_pending",
        message=(
            f"Your simulated contribution of R{parsed_amount:.2f} to {campaign.title} "
            "is awaiting admin review. It is not included in campaign progress yet."
        ),
    )
    session.commit()
    return RedirectResponse("/account/notifications?submitted=1", status_code=303)
