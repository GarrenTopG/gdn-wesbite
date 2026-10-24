import re
from datetime import date
from decimal import Decimal, InvalidOperation
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlmodel import Session, select

from app.db.session import get_session
from app.models.entities import Campaign, CampaignStatus, Donation
from app.routers.admin.auth import verify_staff_session
from app.security import (
    add_audit_event,
    add_record_history,
    now_utc,
    permission_required,
)
from app.services.campaigns import refresh_campaign_completion
from app.services.campaigns import notify_user

router = APIRouter(dependencies=[Depends(permission_required("campaigns.write"))])


def _slugify(title: str) -> str:
    clean = re.sub(r"[^\w\s-]", "", title).strip().lower()
    return re.sub(r"[-\s]+", "-", clean)[:220].strip("-") or "campaign"


def _campaign_fields(
    *,
    title: str,
    summary: str,
    story: str,
    image_url: str,
    image_alt: str,
    area: str,
    category: str,
    target_amount: str,
    deadline: str,
) -> dict[str, object]:
    title = title.strip()
    summary = summary.strip()
    story = story.strip()
    area = area.strip()
    category = category.strip()
    image_url = image_url.strip()
    image_alt = image_alt.strip()
    if not title or len(title) > 255 or not summary or not story:
        raise HTTPException(
            status_code=400, detail="Campaign title, summary, and story are required."
        )
    if not area or len(area) > 255 or not category or len(category) > 100:
        raise HTTPException(
            status_code=400, detail="Enter a valid campaign area and category."
        )
    if len(image_url) > 2048 or len(image_alt) > 500:
        raise HTTPException(
            status_code=400, detail="Campaign image details are too long."
        )
    if image_url:
        parsed_url = urlsplit(image_url)
        if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
            raise HTTPException(
                status_code=400, detail="Campaign images must use an HTTP or HTTPS URL."
            )
        if not image_alt:
            raise HTTPException(
                status_code=400,
                detail="Provide descriptive alt text for the campaign image.",
            )
    try:
        target = Decimal(target_amount.strip())
    except (InvalidOperation, ValueError) as exc:
        raise HTTPException(status_code=400, detail="Invalid target amount.") from exc
    if not target.is_finite() or target <= Decimal("0.00"):
        raise HTTPException(
            status_code=400, detail="The campaign target must be greater than zero."
        )
    try:
        rounded_target = target.quantize(Decimal("0.01"))
    except InvalidOperation as exc:
        raise HTTPException(
            status_code=400, detail="Invalid target precision."
        ) from exc
    if rounded_target != target or target > Decimal("9999999999.99"):
        raise HTTPException(
            status_code=400,
            detail="The target must fit the supported currency precision.",
        )
    try:
        parsed_deadline = (
            date.fromisoformat(deadline.strip()) if deadline.strip() else None
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=400, detail="Invalid campaign deadline."
        ) from exc
    return {
        "title": title,
        "summary": summary,
        "story": story,
        "image_url": image_url or None,
        "image_alt": image_alt or None,
        "area": area,
        "category": category,
        "target_amount": target,
        "deadline": parsed_deadline,
    }


def _unique_slug(session: Session, title: str) -> str:
    base = _slugify(title)
    slug = base
    suffix = 2
    while session.exec(select(Campaign.id).where(Campaign.slug == slug)).first():
        suffix_text = f"-{suffix}"
        slug = f"{base[: 255 - len(suffix_text)]}{suffix_text}"
        suffix += 1
    return slug


@router.post("/campaigns/add")
def create_campaign(
    request: Request,
    title: str = Form(...),
    summary: str = Form(...),
    story: str = Form(...),
    image_url: str = Form(""),
    image_alt: str = Form(""),
    area: str = Form(...),
    category: str = Form(...),
    target_amount: str = Form(...),
    deadline: str = Form(""),
    session: Session = Depends(get_session),
):
    if not verify_staff_session(request):
        raise HTTPException(status_code=401, detail="Unauthorized")
    fields = _campaign_fields(
        title=title,
        summary=summary,
        story=story,
        image_url=image_url,
        image_alt=image_alt,
        area=area,
        category=category,
        target_amount=target_amount,
        deadline=deadline,
    )
    staff_user = request.state.staff_user
    campaign = Campaign(
        **fields,
        slug=_unique_slug(session, str(fields["title"])),
        created_by=staff_user.id,
        status=CampaignStatus.DRAFT,
    )
    session.add(campaign)
    session.flush()
    add_record_history(
        session,
        request,
        "campaign",
        campaign.id,
        "campaign_created",
        {"status": campaign.status.value},
    )
    add_audit_event(session, request, "campaign.created", "campaign", campaign.id)
    session.commit()
    return RedirectResponse(url="/admin/dashboard?tab=needs#campaigns", status_code=303)


@router.post("/campaigns/{campaign_id}/edit")
def edit_campaign(
    campaign_id: int,
    request: Request,
    title: str = Form(...),
    summary: str = Form(...),
    story: str = Form(...),
    image_url: str = Form(""),
    image_alt: str = Form(""),
    area: str = Form(...),
    category: str = Form(...),
    target_amount: str = Form(...),
    deadline: str = Form(""),
    session: Session = Depends(get_session),
):
    if not verify_staff_session(request):
        raise HTTPException(status_code=401, detail="Unauthorized")
    campaign = session.get(Campaign, campaign_id)
    if not campaign or campaign.archived_at is not None:
        raise HTTPException(status_code=404, detail="Campaign not found.")
    fields = _campaign_fields(
        title=title,
        summary=summary,
        story=story,
        image_url=image_url,
        image_alt=image_alt,
        area=area,
        category=category,
        target_amount=target_amount,
        deadline=deadline,
    )
    for name, value in fields.items():
        setattr(campaign, name, value)
    session.add(campaign)
    refresh_campaign_completion(session, request, campaign)
    add_record_history(
        session,
        request,
        "campaign",
        campaign_id,
        "campaign_updated",
        {"title": campaign.title, "target_amount": str(campaign.target_amount)},
    )
    add_audit_event(session, request, "campaign.updated", "campaign", campaign_id)
    session.commit()
    return RedirectResponse(url="/admin/dashboard?tab=needs#campaigns", status_code=303)


@router.post("/campaigns/{campaign_id}/status")
def update_campaign_status(
    campaign_id: int,
    request: Request,
    status: str = Form(...),
    session: Session = Depends(get_session),
):
    if not verify_staff_session(request):
        raise HTTPException(status_code=401, detail="Unauthorized")
    campaign = session.get(Campaign, campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found.")
    try:
        next_status = CampaignStatus(status)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid campaign status.") from exc
    allowed_transitions = {
        CampaignStatus.DRAFT: {CampaignStatus.PUBLISHED, CampaignStatus.ARCHIVED},
        CampaignStatus.PUBLISHED: {CampaignStatus.PAUSED, CampaignStatus.ARCHIVED},
        CampaignStatus.PAUSED: {CampaignStatus.PUBLISHED, CampaignStatus.ARCHIVED},
        CampaignStatus.COMPLETED: {CampaignStatus.ARCHIVED},
        CampaignStatus.ARCHIVED: set(),
    }
    if next_status not in allowed_transitions[campaign.status]:
        raise HTTPException(
            status_code=409,
            detail=f"Invalid campaign status transition from {campaign.status.value}.",
        )
    if next_status == CampaignStatus.PUBLISHED:
        from app.services.campaigns import campaign_raised_amount

        if campaign_raised_amount(session, campaign) >= campaign.target_amount:
            raise HTTPException(
                status_code=409,
                detail="A campaign that has reached its target cannot be reopened.",
            )
        campaign.published_at = campaign.published_at or now_utc()
    if next_status == CampaignStatus.ARCHIVED:
        campaign.archived_at = now_utc()
    previous_status = campaign.status
    campaign.status = next_status
    session.add(campaign)
    add_record_history(
        session,
        request,
        "campaign",
        campaign_id,
        "status_changed",
        {"from": previous_status.value, "to": next_status.value},
    )
    add_audit_event(
        session,
        request,
        "campaign.status_changed",
        "campaign",
        campaign_id,
        {"from": previous_status.value, "to": next_status.value},
    )
    campaign_event = {
        CampaignStatus.PAUSED: (
            "campaign_paused",
            f"{campaign.title} has been temporarily paused. New simulated contributions are not being accepted.",
        ),
        CampaignStatus.PUBLISHED: (
            "campaign_resumed",
            f"{campaign.title} is open for simulated contributions again.",
        ),
        CampaignStatus.ARCHIVED: (
            "campaign_archived",
            f"{campaign.title} has been archived. Its public campaign page is no longer available.",
        ),
    }.get(next_status)
    if campaign_event:
        event_type, message = campaign_event
        contributor_ids = session.exec(
            select(Donation.user_id)
            .where(
                Donation.campaign_id == campaign_id,
                Donation.user_id.is_not(None),
                Donation.status.not_in(
                    (
                        "Rejected",
                        "Refunded",
                    )
                ),
            )
            .distinct()
        ).all()
        for user_id in set(contributor_ids):
            if user_id is not None:
                notify_user(
                    session,
                    user_id=user_id,
                    campaign_id=campaign_id,
                    event_type=event_type,
                    message=message,
                )
    session.commit()
    return RedirectResponse(url="/admin/dashboard?tab=needs#campaigns", status_code=303)
