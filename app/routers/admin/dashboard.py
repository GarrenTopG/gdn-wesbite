import hashlib
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from typing import Dict, NotRequired, Optional, TypedDict

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse
from sqlalchemy import false, true
from sqlmodel import Session, func, select

from app.db.session import get_session
from app.models.entities import (
    BeneficiaryNeed,
    Campaign,
    Donation,
    DonationAllocation,
    DonationStatus,
    NeedStatus,
    NeedUrgency,
    NewsArticle,
    NewsStatus,
    RecordHistory,
    StaffNotificationRead,
    User,
    UserRole,
    Volunteer,
    VolunteerOffer,
)
from app.security import (
    add_audit_event,
    now_utc,
    permission_required,
    role_has_permission,
)
from app.services.campaigns import campaign_progress_by_id
from app.templatesconfig import templates

router = APIRouter()


class NotificationItem(TypedDict):
    key: str
    label: str
    count: int
    tab: str
    fingerprint: str
    is_read: NotRequired[bool]


NOTIFICATION_PERMISSIONS = {
    "volunteers": "volunteers.read",
    "donations": "donations.read",
    "beneficiaries": "beneficiaries.read",
    "needs": "needs.read",
    "volunteer_offers": "needs.read",
}


def _notification_fingerprint(record_ids: list[Optional[int]]) -> str:
    identifiers = ",".join(
        str(record_id)
        for record_id in sorted(
            record_id for record_id in record_ids if record_id is not None
        )
    )
    return hashlib.sha256(identifiers.encode("utf-8")).hexdigest()


def _overview_dashboard(
    request: Request,
    session: Session,
    staff_user: User,
    date_from: date,
    date_to: date,
    active_tab: str = "overview",
) -> HTMLResponse:
    can_view_volunteers = role_has_permission(staff_user.role, "volunteers.read")
    can_view_donations = role_has_permission(staff_user.role, "donations.read")
    can_view_beneficiaries = role_has_permission(staff_user.role, "beneficiaries.read")
    can_view_needs = role_has_permission(staff_user.role, "needs.read")
    can_view_campaigns = role_has_permission(staff_user.role, "campaigns.read")
    can_view_news = role_has_permission(staff_user.role, "news.read")
    can_view_reports = role_has_permission(staff_user.role, "reports.read")
    is_read_only = staff_user.role == UserRole.READ_ONLY
    start_at = datetime.combine(date_from, time.min)
    end_at = datetime.combine(date_to + timedelta(days=1), time.min)
    queue_now = now_utc().replace(tzinfo=None)

    months = []
    month = date_from.replace(day=1)
    final_month = date_to.replace(day=1)
    while month <= final_month:
        months.append(month)
        month = (month.replace(day=28) + timedelta(days=4)).replace(day=1)
    month_keys = [item.strftime("%Y-%m") for item in months]
    chart_month_labels = [item.strftime("%b %Y") for item in months]
    volunteer_counts = dict.fromkeys(month_keys, 0)
    donation_totals = dict.fromkeys(month_keys, Decimal("0.00"))

    volunteer_activity = []
    upcoming_volunteers = []
    pending_volunteer_ids: list[Optional[int]] = []
    if can_view_volunteers:
        volunteer_activity = session.exec(
            select(Volunteer.created_at).where(
                Volunteer.archived_at.is_(None),
                Volunteer.created_at >= start_at,
                Volunteer.created_at < end_at,
            )
        ).all()
        upcoming_volunteers = session.exec(
            select(Volunteer.full_name, Volunteer.next_assignment_at)
            .where(
                Volunteer.archived_at.is_(None),
                Volunteer.next_assignment_at.is_not(None),
                Volunteer.next_assignment_at >= queue_now,
                Volunteer.next_assignment_at <= queue_now + timedelta(days=7),
            )
            .order_by(Volunteer.next_assignment_at)
        ).all()
        pending_volunteer_ids = session.exec(
            select(Volunteer.id).where(
                Volunteer.archived_at.is_(None),
                Volunteer.onboarding_status == "Pending",
            )
        ).all()

    donation_activity = []
    unverified_donations = []
    pending_donation_ids: list[Optional[int]] = []
    total_donation_amount = Decimal("0.00")
    if can_view_donations:
        donation_activity = session.exec(
            select(
                Donation.created_at,
                Donation.amount,
                Donation.is_verified,
                Donation.status,
                Donation.donation_type,
                Donation.campaign_id,
            ).where(
                Donation.created_at >= start_at,
                Donation.created_at < end_at,
                Donation.archived_at.is_(None),
            )
        ).all()
        unverified_donations = session.exec(
            select(Donation.id, Donation.status)
            .where(
                Donation.archived_at.is_(None),
                Donation.status.in_(
                    [
                        DonationStatus.SUBMITTED.value,
                        DonationStatus.PAYMENT_PENDING.value,
                    ]
                ),
            )
            .order_by(Donation.id.desc())
        ).all()
        pending_donation_ids = [row[0] for row in unverified_donations]

    pending_beneficiary_ids: list[Optional[int]] = []
    pending_need_ids: list[Optional[int]] = []
    urgent_assistance = []
    overdue_followups = []
    if can_view_beneficiaries:
        pending_beneficiary_ids = session.exec(
            select(BeneficiaryNeed.id).where(
                BeneficiaryNeed.is_community_need == false(),
                BeneficiaryNeed.archived_at.is_(None),
                BeneficiaryNeed.status == NeedStatus.PENDING,
            )
        ).all()
        urgent_rows = session.exec(
            select(
                BeneficiaryNeed.id,
                BeneficiaryNeed.anonymised_title,
                BeneficiaryNeed.area,
                BeneficiaryNeed.urgency,
            )
            .where(
                BeneficiaryNeed.is_community_need == false(),
                BeneficiaryNeed.archived_at.is_(None),
                BeneficiaryNeed.urgency.in_([NeedUrgency.HIGH, NeedUrgency.CRITICAL]),
                BeneficiaryNeed.status.notin_(
                    [NeedStatus.FULFILLED, NeedStatus.REJECTED]
                ),
            )
            .order_by(BeneficiaryNeed.created_at.desc())
        ).all()
        urgent_assistance = [
            SimpleNamespace(
                id=row[0],
                anonymised_title=row[1],
                area=row[2],
                urgency=row[3],
            )
            for row in urgent_rows
        ]
        overdue_rows = session.exec(
            select(
                BeneficiaryNeed.id,
                BeneficiaryNeed.anonymised_title,
                BeneficiaryNeed.follow_up_at,
            )
            .where(
                BeneficiaryNeed.is_community_need == false(),
                BeneficiaryNeed.archived_at.is_(None),
                BeneficiaryNeed.follow_up_at.is_not(None),
                BeneficiaryNeed.follow_up_at < queue_now,
                BeneficiaryNeed.status.notin_(
                    [NeedStatus.FULFILLED, NeedStatus.REJECTED]
                ),
            )
            .order_by(BeneficiaryNeed.follow_up_at)
        ).all()
        overdue_followups = [
            SimpleNamespace(id=row[0], anonymised_title=row[1], follow_up_at=row[2])
            for row in overdue_rows
        ]
    if can_view_needs:
        pending_need_ids = session.exec(
            select(BeneficiaryNeed.id).where(
                BeneficiaryNeed.is_community_need == true(),
                BeneficiaryNeed.archived_at.is_(None),
                BeneficiaryNeed.status == NeedStatus.PENDING,
            )
        ).all()
    pending_offer_ids = (
        session.exec(
            select(VolunteerOffer.id).where(VolunteerOffer.status == "Pending")
        ).all()
        if can_view_needs
        else []
    )

    pending_donations = len(pending_donation_ids)
    pending_beneficiaries = len(pending_beneficiary_ids)
    pending_needs = len(pending_need_ids)
    volunteer_offer_count = len(pending_offer_ids)

    total_volunteers = len(volunteer_activity)
    if is_read_only:
        total_volunteers = session.exec(
            select(func.count(Volunteer.id)).where(
                Volunteer.archived_at.is_(None),
                Volunteer.created_at >= start_at,
                Volunteer.created_at < end_at,
            )
        ).one()
    for created_at in volunteer_activity:
        key = created_at.strftime("%Y-%m")
        if key in volunteer_counts:
            volunteer_counts[key] += 1

    has_verified_donation_activity = False
    for (
        created_at,
        amount,
        is_verified,
        status_value,
        donation_type,
        campaign_id,
    ) in donation_activity:
        if (
            is_verified
            and status_value != DonationStatus.REFUNDED.value
            and donation_type == "monetary"
            and campaign_id is None
            and amount
        ):
            total_donation_amount += amount
            key = created_at.strftime("%Y-%m")
            if key in donation_totals:
                donation_totals[key] += amount
            has_verified_donation_activity = True
    if is_read_only:
        total_donation_amount = session.exec(
            select(func.coalesce(func.sum(Donation.amount), 0)).where(
                Donation.is_verified == true(),
                Donation.status != DonationStatus.REFUNDED.value,
                Donation.donation_type == "monetary",
                Donation.campaign_id.is_(None),
                Donation.created_at >= start_at,
                Donation.created_at < end_at,
            )
        ).one()

    total_requests = (
        session.exec(
            select(func.count(BeneficiaryNeed.id)).where(
                BeneficiaryNeed.is_community_need == false(),
                BeneficiaryNeed.archived_at.is_(None),
                BeneficiaryNeed.created_at >= start_at,
                BeneficiaryNeed.created_at < end_at,
            )
        ).one()
        if can_view_beneficiaries or is_read_only
        else 0
    )
    total_news = (
        session.exec(
            select(func.count(NewsArticle.id)).where(
                NewsArticle.status == NewsStatus.PUBLISHED.value,
                NewsArticle.archived_at.is_(None),
                NewsArticle.created_at >= start_at,
                NewsArticle.created_at < end_at,
            )
        ).one()
        if can_view_news or is_read_only
        else 0
    )

    notification_items: list[NotificationItem] = []
    pending_groups = [
        (
            can_view_volunteers,
            "volunteers",
            "Volunteer applications to review",
            pending_volunteer_ids,
            "volunteers",
        ),
        (
            can_view_donations,
            "donations",
            "Donation pledges to review",
            pending_donation_ids,
            "donations",
        ),
        (
            can_view_beneficiaries,
            "beneficiaries",
            "Assistance requests to review",
            pending_beneficiary_ids,
            "beneficiaries",
        ),
        (
            can_view_needs,
            "needs",
            "Community needs to review",
            pending_need_ids,
            "needs",
        ),
        (
            can_view_needs,
            "volunteer_offers",
            "Volunteer offers to review",
            pending_offer_ids,
            "needs",
        ),
    ]
    notification_items = [
        {
            "key": key,
            "label": label,
            "count": len(record_ids),
            "tab": tab,
            "fingerprint": _notification_fingerprint(record_ids),
        }
        for visible, key, label, record_ids, tab in pending_groups
        if visible and record_ids
    ]
    notification_reads = {
        item.notification_key: item.fingerprint
        for item in session.exec(
            select(StaffNotificationRead).where(
                StaffNotificationRead.staff_user_id == staff_user.id
            )
        ).all()
    }
    for item in notification_items:
        item["is_read"] = notification_reads.get(item["key"]) == item["fingerprint"]
    unread_notification_count = sum(
        item["count"] for item in notification_items if not item.get("is_read", False)
    )

    visible_areas = [
        name
        for name, visible in (
            ("volunteers", can_view_volunteers),
            ("donations", can_view_donations),
            ("beneficiaries", can_view_beneficiaries),
            ("needs", can_view_needs),
            ("campaigns", can_view_campaigns),
            ("news", can_view_news),
            ("aggregate_reports", is_read_only),
        )
        if visible
    ]
    add_audit_event(
        session,
        request,
        "dashboard.view",
        "admin_dashboard",
        details={"role": staff_user.role.value, "visible_areas": visible_areas},
    )
    session.commit()

    return templates.TemplateResponse(
        request=request,
        name="admindashboard.html",
        context={
            "active_page": "admin",
            "active_tab": active_tab,
            "volunteers": [],
            "filtered_volunteers": [],
            "donations": [],
            "needs": [],
            "volunteer_offers": [],
            "allocation_needs": [],
            "beneficiaries": [],
            "news_articles": [],
            "campaigns": [],
            "campaign_progress": {},
            "campaigns_by_id": {},
            "donation_needs_by_id": {},
            "notification_items": notification_items,
            "notification_count": unread_notification_count,
            "staff_user": staff_user,
            "can_view_volunteers": can_view_volunteers,
            "can_view_donations": can_view_donations,
            "can_view_beneficiaries": can_view_beneficiaries,
            "can_view_needs": can_view_needs,
            "can_view_campaigns": can_view_campaigns,
            "can_view_news": can_view_news,
            "can_view_reports": can_view_reports,
            "can_write_needs": role_has_permission(staff_user.role, "needs.write"),
            "can_write_campaigns": role_has_permission(
                staff_user.role, "campaigns.write"
            ),
            "can_export_volunteers": role_has_permission(
                staff_user.role, "exports.volunteers"
            ),
            "can_export_donations": role_has_permission(
                staff_user.role, "exports.donations"
            ),
            "can_export_needs": role_has_permission(staff_user.role, "exports.needs"),
            "can_export_beneficiaries": role_has_permission(
                staff_user.role, "exports.beneficiaries"
            ),
            "is_administrator": staff_user.role == UserRole.ADMINISTRATOR,
            "is_read_only": is_read_only,
            "total_volunteers": total_volunteers,
            "total_donation_amount": f"{total_donation_amount:.2f}",
            "total_requests": total_requests,
            "total_news": total_news,
            "need_funding_progress": {},
            "need_history": {},
            "chart_month_labels": chart_month_labels,
            "monthly_volunteer_counts": [volunteer_counts[key] for key in month_keys],
            "monthly_verified_donations": [
                float(donation_totals[key]) for key in month_keys
            ],
            "has_volunteer_activity": bool(volunteer_activity),
            "has_verified_donation_activity": has_verified_donation_activity,
            "date_from": date_from.isoformat(),
            "date_to": date_to.isoformat(),
            "pending_donations": pending_donations,
            "pending_beneficiaries": pending_beneficiaries,
            "pending_needs": pending_needs,
            "pending_work_count": sum(
                (
                    len(urgent_assistance),
                    len(unverified_donations),
                    len(upcoming_volunteers),
                    len(overdue_followups),
                    volunteer_offer_count,
                )
            ),
            "urgent_assistance": urgent_assistance,
            "unverified_donations": [
                SimpleNamespace(id=row[0], status=row[1])
                for row in unverified_donations
            ],
            "upcoming_volunteers": [
                SimpleNamespace(full_name=row[0], next_assignment_at=row[1])
                for row in upcoming_volunteers
            ],
            "overdue_followups": overdue_followups,
            "assistance_filters": {
                "status": "",
                "urgency": "",
                "category": "",
                "region": "",
            },
            "volunteer_filters": {
                "skills": "",
                "location": "",
                "availability": "",
                "onboarding": "",
            },
            "include_archived": False,
            "need_statuses": list(NeedStatus),
            "need_urgencies": list(NeedUrgency),
        },
    )


@router.get("/dashboard", response_class=HTMLResponse)
def get_admin_dashboard(
    request: Request,
    session: Session = Depends(get_session),
    staff_user: User = Depends(permission_required("dashboard")),
):

    from sqlmodel import col

    today = now_utc().date()
    default_start = today - timedelta(days=29)
    try:
        from_value = request.query_params.get("from", default_start.isoformat())
        to_value = request.query_params.get("to", today.isoformat())
        date_from = date.fromisoformat(from_value)
        date_to = date.fromisoformat(to_value)
        if date_from.isoformat() != from_value or date_to.isoformat() != to_value:
            raise ValueError("Dates must use the YYYY-MM-DD format.")
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Date filters must use YYYY-MM-DD.",
        ) from exc
    if date_from > date_to:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="The start date must be on or before the end date.",
        )

    can_view_volunteers = role_has_permission(staff_user.role, "volunteers.read")
    can_view_donations = role_has_permission(staff_user.role, "donations.read")
    can_view_beneficiaries = role_has_permission(staff_user.role, "beneficiaries.read")
    can_view_needs = role_has_permission(staff_user.role, "needs.read")
    can_view_campaigns = role_has_permission(staff_user.role, "campaigns.read")
    can_view_news = role_has_permission(staff_user.role, "news.read")
    can_view_reports = role_has_permission(staff_user.role, "reports.read")
    active_tab = request.query_params.get("tab", "overview")
    tab_permissions = {
        "overview": True,
        "volunteers": can_view_volunteers,
        "donations": can_view_donations,
        "beneficiaries": can_view_beneficiaries,
        "needs": can_view_needs,
        "news": can_view_news,
        "reports": can_view_reports,
    }
    if not tab_permissions.get(active_tab, False):
        active_tab = "overview"
    if active_tab in {"overview", "reports"}:
        return _overview_dashboard(
            request, session, staff_user, date_from, date_to, active_tab
        )

    include_archived = (
        request.query_params.get("include_archived", "").lower() == "true"
    )

    volunteers = (
        session.exec(
            select(Volunteer)
            .where(True if include_archived else Volunteer.archived_at.is_(None))
            .order_by(Volunteer.id.desc())
        ).all()
        if can_view_volunteers and active_tab == "volunteers"
        else []
    )
    donation_activity = (
        session.exec(select(Donation).order_by(col(Donation.id).desc())).all()
        if can_view_donations and active_tab == "donations"
        else []
    )
    donations = [
        donation
        for donation in donation_activity
        if include_archived or donation.archived_at is None
    ]
    if can_view_beneficiaries and active_tab == "beneficiaries":
        all_needs = session.exec(
            select(BeneficiaryNeed).where(
                BeneficiaryNeed.is_community_need == false(),
                True if include_archived else BeneficiaryNeed.archived_at.is_(None),
            )
        ).all()
    elif can_view_needs and active_tab == "needs":
        need_rows = session.exec(
            select(
                BeneficiaryNeed.id,
                BeneficiaryNeed.is_community_need,
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
                BeneficiaryNeed.archived_at,
                BeneficiaryNeed.created_at,
            ).where(
                BeneficiaryNeed.is_community_need == true(),
                True if include_archived else BeneficiaryNeed.archived_at.is_(None),
            )
        ).all()
        all_needs = [
            SimpleNamespace(
                id=row[0],
                is_community_need=row[1],
                anonymised_title=row[2],
                area=row[3],
                category=row[4],
                urgency=row[5],
                status=row[6],
                target_amount=row[7],
                current_amount=row[8],
                article=row[9],
                image_url=row[10],
                image_alt=row[11],
                deadline=row[12],
                archived_at=row[13],
                created_at=row[14],
            )
            for row in need_rows
        ]
    else:
        all_needs = []
    news_articles = (
        session.exec(select(NewsArticle)).all()
        if can_view_news and active_tab == "news"
        else []
    )
    campaigns = (
        session.exec(
            select(Campaign)
            .where(True if include_archived else Campaign.archived_at.is_(None))
            .order_by(Campaign.created_at.desc())
        ).all()
        if can_view_campaigns and active_tab == "needs"
        else []
    )
    campaign_progress = (
        campaign_progress_by_id(session, campaigns) if active_tab == "needs" else {}
    )
    donation_campaign_ids = {
        donation.campaign_id
        for donation in donations
        if donation.campaign_id is not None
    }
    campaigns_by_id = (
        {
            campaign.id: campaign
            for campaign in session.exec(
                select(Campaign).where(Campaign.id.in_(donation_campaign_ids))
            ).all()
            if campaign.id is not None
        }
        if active_tab == "donations" and donation_campaign_ids
        else {}
    )
    donation_need_ids = {
        donation.need_id for donation in donations if donation.need_id is not None
    }
    donation_needs_by_id = (
        {
            need.id: need
            for need in session.exec(
                select(BeneficiaryNeed).where(BeneficiaryNeed.id.in_(donation_need_ids))
            ).all()
            if need.id is not None
        }
        if active_tab == "donations" and donation_need_ids
        else {}
    )

    beneficiaries = [need for need in all_needs if not need.is_community_need]
    community_needs = [need for need in all_needs if need.is_community_need]
    allocation_needs = [
        need
        for need in community_needs
        if need.archived_at is None
        and need.status != NeedStatus.REJECTED
        and (
            need.target_amount is None
            or need.target_amount <= Decimal("0.00")
            or (need.current_amount or Decimal("0.00")) < need.target_amount
        )
    ]

    assistance_status = request.query_params.get("request_status", "").strip()
    assistance_urgency = request.query_params.get("request_urgency", "").strip()
    assistance_category = request.query_params.get("request_category", "").strip()
    assistance_region = request.query_params.get("request_region", "").strip()
    known_statuses = {value.value for value in NeedStatus}
    known_urgencies = {value.value for value in NeedUrgency}
    if assistance_status and assistance_status not in known_statuses:
        raise HTTPException(status_code=422, detail="Invalid assistance status filter.")
    if assistance_urgency and assistance_urgency not in known_urgencies:
        raise HTTPException(status_code=422, detail="Invalid urgency filter.")
    filtered_beneficiaries = [
        need
        for need in beneficiaries
        if (
            not assistance_status
            or getattr(need.status, "value", need.status) == assistance_status
        )
        and (
            not assistance_urgency
            or getattr(need.urgency, "value", need.urgency) == assistance_urgency
        )
        and (
            not assistance_category
            or assistance_category.casefold() in need.category.casefold()
        )
        and (
            not assistance_region
            or assistance_region.casefold() in need.area.casefold()
        )
        and date_from <= need.created_at.date() <= date_to
    ]
    volunteer_skills = request.query_params.get("volunteer_skills", "").strip()
    volunteer_location = request.query_params.get("volunteer_location", "").strip()
    volunteer_availability = request.query_params.get(
        "volunteer_availability", ""
    ).strip()
    volunteer_onboarding = request.query_params.get("volunteer_onboarding", "").strip()
    filtered_volunteers = [
        volunteer
        for volunteer in volunteers
        if (
            not volunteer_skills
            or volunteer_skills.casefold() in volunteer.skills.casefold()
        )
        and (
            not volunteer_location
            or volunteer_location.casefold() in volunteer.location.casefold()
        )
        and (
            not volunteer_availability
            or volunteer_availability.casefold() in volunteer.availability.casefold()
            or volunteer_availability.casefold()
            in ", ".join(volunteer.available_days or []).casefold()
        )
        and (
            not volunteer_onboarding
            or volunteer.onboarding_status == volunteer_onboarding
        )
    ]

    def is_in_date_range(record) -> bool:
        created_at = record.created_at
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        return date_from <= created_at.date() <= date_to

    range_volunteers = [
        record
        for record in volunteers
        if record.archived_at is None and is_in_date_range(record)
    ]
    range_donations = [
        record for record in donation_activity if is_in_date_range(record)
    ]
    range_beneficiaries = [
        record
        for record in beneficiaries
        if record.archived_at is None and is_in_date_range(record)
    ]
    range_news_articles = [
        record
        for record in news_articles
        if is_in_date_range(record)
        and record.status == NewsStatus.PUBLISHED.value
        and record.archived_at is None
    ]

    total_donation_amount = sum(
        (
            donation.amount
            for donation in range_donations
            if donation.amount
            and donation.is_verified
            and donation.status != DonationStatus.REFUNDED.value
            and donation.donation_type == "monetary"
            and donation.campaign_id is None
        ),
        Decimal("0.00"),
    )
    if staff_user.role == UserRole.READ_ONLY:
        date_filter = func.date(Volunteer.created_at)
        total_volunteers = session.exec(
            select(func.count(Volunteer.id)).where(
                Volunteer.archived_at.is_(None),
                date_filter >= date_from.isoformat(),
                date_filter <= date_to.isoformat(),
            )
        ).one()
        donation_date = func.date(Donation.created_at)
        total_donation_amount = session.exec(
            select(func.coalesce(func.sum(Donation.amount), 0)).where(
                Donation.is_verified == true(),
                Donation.status != DonationStatus.REFUNDED.value,
                Donation.donation_type == "monetary",
                Donation.campaign_id.is_(None),
                donation_date >= date_from.isoformat(),
                donation_date <= date_to.isoformat(),
            )
        ).one()
        request_date = func.date(BeneficiaryNeed.created_at)
        total_requests = session.exec(
            select(func.count(BeneficiaryNeed.id)).where(
                BeneficiaryNeed.is_community_need == false(),
                BeneficiaryNeed.archived_at.is_(None),
                request_date >= date_from.isoformat(),
                request_date <= date_to.isoformat(),
            )
        ).one()
        news_date = func.date(NewsArticle.created_at)
        total_news = session.exec(
            select(func.count(NewsArticle.id)).where(
                NewsArticle.status == NewsStatus.PUBLISHED.value,
                NewsArticle.archived_at.is_(None),
                news_date >= date_from.isoformat(),
                news_date <= date_to.isoformat(),
            )
        ).one()
    else:
        total_volunteers = len(range_volunteers)
        total_requests = len(range_beneficiaries)
        total_news = len(range_news_articles)
    allocation_totals: dict[int, Decimal] = {}
    funding_need_ids = [need.id for need in community_needs if need.id is not None]
    if can_view_donations and funding_need_ids:
        funding_rows = session.exec(
            select(
                DonationAllocation.need_id,
                func.sum(DonationAllocation.amount),
            )
            .join(Donation, Donation.id == DonationAllocation.donation_id)
            .where(
                DonationAllocation.need_id.in_(funding_need_ids),
                Donation.is_verified == true(),
                Donation.status != DonationStatus.REFUNDED.value,
            )
            .group_by(DonationAllocation.need_id)
        ).all()
        allocation_totals = {
            row[0]: Decimal(str(row[1] or "0.00")) for row in funding_rows
        }

    need_funding_progress: Dict[int, Dict[str, Decimal]] = {}
    for need in all_needs:
        if need.id is None:
            continue
        raised = (
            allocation_totals.get(need.id, Decimal("0.00"))
            if can_view_donations
            else (need.current_amount or Decimal("0.00"))
        )
        target = need.target_amount or Decimal("0.00")
        percent = (
            raised / target * Decimal("100.0")
            if target > Decimal("0.00")
            else Decimal("0.0")
        )
        need_funding_progress[need.id] = {
            "raised": raised,
            "target": target,
            "percentage": min(percent, Decimal("100.0")),
        }

    first_month = date_from.replace(day=1)
    final_month = date_to.replace(day=1)
    months = []
    month = first_month
    while month <= final_month:
        months.append(month)
        month = (month.replace(day=28) + timedelta(days=4)).replace(day=1)
    chart_month_labels = [month.strftime("%b %Y") for month in months]

    def month_counts(records):
        counts = {month.strftime("%Y-%m"): 0 for month in months}
        for record in records:
            key = record.created_at.strftime("%Y-%m")
            if key in counts:
                counts[key] += 1
        return [counts[month.strftime("%Y-%m")] for month in months]

    monthly_volunteer_counts = month_counts(range_volunteers)
    monthly_verified_donations = []
    for month in months:
        monthly_verified_donations.append(
            float(
                sum(
                    (
                        donation.amount
                        for donation in range_donations
                        if donation.is_verified
                        and donation.status != DonationStatus.REFUNDED.value
                        and donation.donation_type == "monetary"
                        and donation.campaign_id is None
                        and donation.created_at.strftime("%Y-%m")
                        == month.strftime("%Y-%m")
                    ),
                    Decimal("0.00"),
                )
            )
        )

    pending_donations = sum(
        donation.archived_at is None
        and donation.status
        in {
            DonationStatus.SUBMITTED.value,
            DonationStatus.PAYMENT_PENDING.value,
        }
        for donation in donations
    )
    pending_beneficiaries = sum(
        need.archived_at is None and need.status == NeedStatus.PENDING
        for need in beneficiaries
    )
    pending_needs = sum(
        need.archived_at is None and need.status == NeedStatus.PENDING
        for need in community_needs
    )
    urgent_assistance = [
        need
        for need in beneficiaries
        if need.archived_at is None
        and need.urgency in {NeedUrgency.HIGH, NeedUrgency.CRITICAL}
        and need.status not in {NeedStatus.FULFILLED, NeedStatus.REJECTED}
    ]
    unverified_donations = [
        donation
        for donation in donations
        if donation.archived_at is None
        and donation.status
        in {
            DonationStatus.SUBMITTED.value,
            DonationStatus.PAYMENT_PENDING.value,
        }
    ]
    queue_now = now_utc()
    upcoming_volunteers = [
        volunteer
        for volunteer in volunteers
        if volunteer.archived_at is None
        and volunteer.next_assignment_at is not None
        and queue_now
        <= (
            volunteer.next_assignment_at.replace(tzinfo=timezone.utc)
            if volunteer.next_assignment_at.tzinfo is None
            else volunteer.next_assignment_at
        )
        <= queue_now + timedelta(days=7)
    ]
    overdue_followups = [
        need
        for need in beneficiaries
        if need.archived_at is None
        and need.follow_up_at is not None
        and (
            need.follow_up_at.replace(tzinfo=timezone.utc)
            if need.follow_up_at.tzinfo is None
            else need.follow_up_at
        )
        < queue_now
        and need.status not in {NeedStatus.FULFILLED, NeedStatus.REJECTED}
    ]
    community_need_ids = [need.id for need in community_needs if need.id is not None]
    volunteer_offers = []
    if can_view_needs and active_tab == "needs":
        offer_rows = session.exec(
            select(
                VolunteerOffer,
                User.full_name,
                User.email,
                BeneficiaryNeed.anonymised_title,
            )
            .join(User, User.id == VolunteerOffer.user_id)
            .join(BeneficiaryNeed, BeneficiaryNeed.id == VolunteerOffer.need_id)
            .order_by(VolunteerOffer.created_at.desc())
        ).all()
        volunteer_offers = [
            SimpleNamespace(
                id=offer.id,
                need_id=offer.need_id,
                need_title=need_title,
                full_name=full_name,
                email=email,
                volunteer_skill=offer.volunteer_skill,
                notes=offer.notes,
                status=offer.status,
                created_at=offer.created_at,
            )
            for offer, full_name, email, need_title in offer_rows
        ]
    pending_volunteer_offers = [
        offer for offer in volunteer_offers if offer.status == "Pending"
    ]
    pending_groups = [
        (
            can_view_volunteers,
            "volunteers",
            "Volunteer applications to review",
            session.exec(
                select(Volunteer.id).where(
                    Volunteer.archived_at.is_(None),
                    Volunteer.onboarding_status == "Pending",
                )
            ).all()
            if can_view_volunteers
            else [],
            "volunteers",
        ),
        (
            can_view_donations,
            "donations",
            "Donation pledges to review",
            session.exec(
                select(Donation.id).where(
                    Donation.archived_at.is_(None),
                    Donation.status.in_(
                        [
                            DonationStatus.SUBMITTED.value,
                            DonationStatus.PAYMENT_PENDING.value,
                        ]
                    ),
                )
            ).all()
            if can_view_donations
            else [],
            "donations",
        ),
        (
            can_view_beneficiaries,
            "beneficiaries",
            "Assistance requests to review",
            session.exec(
                select(BeneficiaryNeed.id).where(
                    BeneficiaryNeed.is_community_need == false(),
                    BeneficiaryNeed.archived_at.is_(None),
                    BeneficiaryNeed.status == NeedStatus.PENDING,
                )
            ).all()
            if can_view_beneficiaries
            else [],
            "beneficiaries",
        ),
        (
            can_view_needs,
            "needs",
            "Community needs to review",
            session.exec(
                select(BeneficiaryNeed.id).where(
                    BeneficiaryNeed.is_community_need == true(),
                    BeneficiaryNeed.archived_at.is_(None),
                    BeneficiaryNeed.status == NeedStatus.PENDING,
                )
            ).all()
            if can_view_needs
            else [],
            "needs",
        ),
        (
            can_view_needs,
            "volunteer_offers",
            "Volunteer offers to review",
            session.exec(
                select(VolunteerOffer.id).where(VolunteerOffer.status == "Pending")
            ).all()
            if can_view_needs
            else [],
            "needs",
        ),
    ]
    notification_items: list[NotificationItem] = [
        {
            "key": key,
            "label": label,
            "count": len(record_ids),
            "tab": tab,
            "fingerprint": _notification_fingerprint(record_ids),
        }
        for visible, key, label, record_ids, tab in pending_groups
        if visible and record_ids
    ]
    pending_donations = len(pending_groups[1][3])
    pending_beneficiaries = len(pending_groups[2][3])
    pending_needs = len(pending_groups[3][3])
    notification_reads = {
        item.notification_key: item.fingerprint
        for item in session.exec(
            select(StaffNotificationRead).where(
                StaffNotificationRead.staff_user_id == staff_user.id
            )
        ).all()
    }
    for item in notification_items:
        item["is_read"] = notification_reads.get(item["key"]) == item["fingerprint"]
    unread_notification_count = sum(
        item["count"] for item in notification_items if not item.get("is_read", False)
    )
    need_history: dict[int, list[RecordHistory]] = {}
    if community_need_ids:
        history_rows = session.exec(
            select(RecordHistory)
            .where(
                RecordHistory.record_type == "beneficiary_need",
                RecordHistory.record_id.in_(community_need_ids),
            )
            .order_by(RecordHistory.occurred_at.desc())
        ).all()
        for event in history_rows:
            need_history.setdefault(event.record_id, []).append(event)

    visible_areas = [
        name
        for name, visible in (
            ("volunteers", can_view_volunteers),
            ("donations", can_view_donations),
            ("beneficiaries", can_view_beneficiaries),
            ("needs", can_view_needs),
            ("campaigns", can_view_campaigns),
            ("news", can_view_news),
            ("aggregate_reports", staff_user.role == UserRole.READ_ONLY),
        )
        if visible
    ]
    add_audit_event(
        session,
        request,
        "dashboard.view",
        "admin_dashboard",
        details={"role": staff_user.role.value, "visible_areas": visible_areas},
    )
    session.commit()

    return templates.TemplateResponse(
        request=request,
        name="admindashboard.html",
        context={
            "active_page": "admin",
            "active_tab": active_tab,
            "volunteers": volunteers,
            "filtered_volunteers": filtered_volunteers,
            "donations": donations,
            "needs": community_needs,
            "volunteer_offers": volunteer_offers,
            "allocation_needs": allocation_needs,
            "beneficiaries": filtered_beneficiaries,
            "news_articles": news_articles,
            "campaigns": campaigns,
            "campaign_progress": campaign_progress,
            "campaigns_by_id": campaigns_by_id,
            "donation_needs_by_id": donation_needs_by_id,
            "notification_items": notification_items,
            "notification_count": unread_notification_count,
            "staff_user": request.state.staff_user,
            "can_view_volunteers": can_view_volunteers,
            "can_view_donations": can_view_donations,
            "can_view_beneficiaries": can_view_beneficiaries,
            "can_view_needs": can_view_needs,
            "can_view_campaigns": can_view_campaigns,
            "can_view_news": can_view_news,
            "can_view_reports": can_view_reports,
            "can_write_needs": role_has_permission(staff_user.role, "needs.write"),
            "can_write_campaigns": role_has_permission(
                staff_user.role, "campaigns.write"
            ),
            "can_export_volunteers": role_has_permission(
                staff_user.role, "exports.volunteers"
            ),
            "can_export_donations": role_has_permission(
                staff_user.role, "exports.donations"
            ),
            "can_export_needs": role_has_permission(staff_user.role, "exports.needs"),
            "can_export_beneficiaries": role_has_permission(
                staff_user.role, "exports.beneficiaries"
            ),
            "is_administrator": staff_user.role == UserRole.ADMINISTRATOR,
            "is_read_only": staff_user.role == UserRole.READ_ONLY,
            "total_volunteers": total_volunteers,
            "total_donation_amount": f"{total_donation_amount:.2f}",
            "total_requests": total_requests,
            "total_news": total_news,
            "need_funding_progress": need_funding_progress,
            "need_history": need_history,
            "chart_month_labels": chart_month_labels,
            "monthly_volunteer_counts": monthly_volunteer_counts,
            "monthly_verified_donations": monthly_verified_donations,
            "has_volunteer_activity": bool(range_volunteers),
            "has_verified_donation_activity": any(
                donation.is_verified
                and donation.status != DonationStatus.REFUNDED.value
                and donation.donation_type == "monetary"
                and donation.campaign_id is None
                and donation.amount
                for donation in range_donations
            ),
            "date_from": date_from.isoformat(),
            "date_to": date_to.isoformat(),
            "pending_donations": pending_donations,
            "pending_beneficiaries": pending_beneficiaries,
            "pending_needs": pending_needs,
            "pending_work_count": sum(
                (
                    len(urgent_assistance),
                    len(unverified_donations),
                    len(upcoming_volunteers),
                    len(overdue_followups),
                    len(pending_volunteer_offers),
                )
            ),
            "urgent_assistance": urgent_assistance,
            "unverified_donations": unverified_donations,
            "upcoming_volunteers": upcoming_volunteers,
            "overdue_followups": overdue_followups,
            "assistance_filters": {
                "status": assistance_status,
                "urgency": assistance_urgency,
                "category": assistance_category,
                "region": assistance_region,
            },
            "volunteer_filters": {
                "skills": volunteer_skills,
                "location": volunteer_location,
                "availability": volunteer_availability,
                "onboarding": volunteer_onboarding,
            },
            "include_archived": include_archived,
            "need_statuses": list(NeedStatus),
            "need_urgencies": list(NeedUrgency),
        },
    )
