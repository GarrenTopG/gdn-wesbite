from decimal import Decimal

from sqlalchemy import true
from sqlmodel import Session, select, func
from starlette.requests import Request

from app.models.entities import (
    Campaign,
    CampaignStatus,
    Donation,
    DonationStatus,
    UserNotification,
)
from app.security import add_audit_event, add_record_history, now_utc


def campaign_raised_amount(session: Session, campaign: Campaign) -> Decimal:
    approved_total = session.exec(
        select(func.coalesce(func.sum(Donation.amount), 0)).where(
            Donation.campaign_id == campaign.id,
            Donation.is_verified == true(),
            Donation.status != DonationStatus.REFUNDED.value,
        )
    ).one()
    return Decimal(str(campaign.legacy_raised_amount or "0.00")) + Decimal(
        str(approved_total or "0.00")
    )


def campaign_progress_by_id(
    session: Session, campaigns: list[Campaign]
) -> dict[int, Decimal]:
    campaign_ids = [campaign.id for campaign in campaigns if campaign.id is not None]
    totals: dict[int, Decimal] = {}
    if campaign_ids:
        rows = session.exec(
            select(Donation.campaign_id, func.coalesce(func.sum(Donation.amount), 0))
            .where(
                Donation.campaign_id.in_(campaign_ids),
                Donation.is_verified == true(),
                Donation.status != DonationStatus.REFUNDED.value,
            )
            .group_by(Donation.campaign_id)
        ).all()
        totals = {
            campaign_id: Decimal(str(amount or "0.00"))
            for campaign_id, amount in rows
            if campaign_id is not None
        }
    return {
        campaign.id: Decimal(str(campaign.legacy_raised_amount or "0.00"))
        + totals.get(campaign.id, Decimal("0.00"))
        for campaign in campaigns
        if campaign.id is not None
    }


def notify_user(
    session: Session,
    *,
    user_id: int,
    campaign_id: int,
    event_type: str,
    message: str,
    donation_id: int | None = None,
) -> None:
    session.add(
        UserNotification(
            user_id=user_id,
            donation_id=donation_id,
            campaign_id=campaign_id,
            event_type=event_type,
            message=message,
        )
    )


def refresh_campaign_completion(
    session: Session, request: Request, campaign: Campaign
) -> bool:
    if campaign.id is None or campaign.archived_at is not None:
        return False
    previous_status = campaign.status
    raised = campaign_raised_amount(session, campaign)
    target_reached = campaign.target_amount > Decimal("0.00") and raised >= (
        campaign.target_amount
    )
    if target_reached and campaign.status != CampaignStatus.COMPLETED:
        campaign.completion_return_status = campaign.status.value
        campaign.status = CampaignStatus.COMPLETED
        campaign.completed_at = now_utc()
    elif (
        not target_reached
        and campaign.status == CampaignStatus.COMPLETED
        and campaign.completed_at is not None
    ):
        try:
            return_status = CampaignStatus(
                campaign.completion_return_status or CampaignStatus.PUBLISHED.value
            )
        except ValueError:
            return_status = CampaignStatus.PUBLISHED
        campaign.status = (
            return_status
            if return_status in {CampaignStatus.PUBLISHED, CampaignStatus.PAUSED}
            else CampaignStatus.PUBLISHED
        )
        campaign.completion_return_status = None
        campaign.completed_at = None
    if campaign.status == previous_status:
        return False

    session.add(campaign)
    add_record_history(
        session,
        request,
        "campaign",
        campaign.id,
        "status_changed",
        {
            "from": previous_status.value,
            "to": campaign.status.value,
            "verified_demo_contributions": str(raised),
        },
    )
    add_audit_event(
        session,
        request,
        "campaign.status_changed",
        "campaign",
        campaign.id,
        {"from": previous_status.value, "to": campaign.status.value},
    )
    if campaign.status == CampaignStatus.COMPLETED:
        user_ids = session.exec(
            select(Donation.user_id)
            .where(
                Donation.campaign_id == campaign.id,
                Donation.user_id.is_not(None),
                Donation.is_verified == true(),
                Donation.status != DonationStatus.REFUNDED.value,
            )
            .distinct()
        ).all()
        for user_id in user_ids:
            if user_id is not None:
                notify_user(
                    session,
                    user_id=user_id,
                    campaign_id=campaign.id,
                    event_type="campaign_completed",
                    message=(
                        f"The demo funding goal for {campaign.title} has been reached. "
                        "The campaign is complete and no longer accepts contributions."
                    ),
                )
    return True
