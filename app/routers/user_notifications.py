from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlmodel import Session, select

from app.db.session import get_session
from app.models.entities import BeneficiaryNeed, Campaign, Donation, UserNotification
from app.routers.accounts import get_public_user
from app.security import now_utc, require_csrf
from app.templatesconfig import templates

router = APIRouter(
    prefix="/account/notifications",
    tags=["User notifications"],
    dependencies=[Depends(require_csrf)],
)


def _require_public_user(request: Request, session: Session):
    user = get_public_user(request, session)
    if not user:
        return None
    if user.id is None:
        raise HTTPException(status_code=401, detail="Sign in to view notifications.")
    return user


@router.get("", response_class=HTMLResponse)
def list_user_notifications(
    request: Request,
    session: Session = Depends(get_session),
):
    user = _require_public_user(request, session)
    if not user:
        return RedirectResponse(
            "/account/login?next_path=%2Faccount%2Fnotifications",
            status_code=303,
        )
    items = session.exec(
        select(UserNotification)
        .where(UserNotification.user_id == user.id)
        .order_by(UserNotification.created_at.desc(), UserNotification.id.desc())
        .limit(100)
    ).all()
    campaign_ids = {item.campaign_id for item in items if item.campaign_id is not None}
    campaigns_by_id = (
        {
            campaign.id: campaign
            for campaign in session.exec(
                select(Campaign).where(Campaign.id.in_(campaign_ids))
            ).all()
            if campaign.id is not None
        }
        if campaign_ids
        else {}
    )
    donation_ids = {item.donation_id for item in items if item.donation_id is not None}
    donations_by_id = (
        {
            donation.id: donation
            for donation in session.exec(
                select(Donation).where(Donation.id.in_(donation_ids))
            ).all()
            if donation.id is not None
        }
        if donation_ids
        else {}
    )
    need_ids = {
        donation.need_id
        for donation in donations_by_id.values()
        if donation.need_id is not None
    }
    needs_by_id = (
        {
            need.id: need
            for need in session.exec(
                select(BeneficiaryNeed).where(BeneficiaryNeed.id.in_(need_ids))
            ).all()
            if need.id is not None
        }
        if need_ids
        else {}
    )
    return templates.TemplateResponse(
        request=request,
        name="usernotifications.html",
        context={
            "active_page": "notifications",
            "notifications": items,
            "campaigns_by_id": campaigns_by_id,
            "donations_by_id": donations_by_id,
            "needs_by_id": needs_by_id,
            "submitted": request.query_params.get("submitted") == "1",
        },
        headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"},
    )


@router.post("/read")
def mark_user_notification_read(
    request: Request,
    notification_id: int = Form(...),
    session: Session = Depends(get_session),
):
    user = _require_public_user(request, session)
    if not user:
        return RedirectResponse(
            "/account/login?next_path=%2Faccount%2Fnotifications",
            status_code=303,
        )
    notification = session.exec(
        select(UserNotification).where(
            UserNotification.id == notification_id,
            UserNotification.user_id == user.id,
        )
    ).first()
    if not notification:
        raise HTTPException(status_code=404, detail="Notification not found.")
    if notification.read_at is None:
        notification.read_at = now_utc()
        session.add(notification)
        session.commit()
    return RedirectResponse("/account/notifications", status_code=303)


@router.post("/read-all")
def mark_all_user_notifications_read(
    request: Request,
    session: Session = Depends(get_session),
):
    user = _require_public_user(request, session)
    if not user:
        return RedirectResponse(
            "/account/login?next_path=%2Faccount%2Fnotifications",
            status_code=303,
        )
    unread_items = session.exec(
        select(UserNotification).where(
            UserNotification.user_id == user.id,
            UserNotification.read_at.is_(None),
        )
    ).all()
    read_at = now_utc()
    for notification in unread_items:
        notification.read_at = read_at
        session.add(notification)
    if unread_items:
        session.commit()
    return RedirectResponse("/account/notifications", status_code=303)
