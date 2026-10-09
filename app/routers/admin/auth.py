import hashlib
import secrets
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from sqlmodel import Session, func, select

from app.db.session import get_session
from app.models.entities import (
    AuthSession,
    AuditLog,
    BeneficiaryNeed,
    Donation,
    DonationAllocation,
    DonationStatus,
    NeedStatus,
    NeedUrgency,
    NewsStatus,
    RecordHistory,
    User,
    UserRole,
    Volunteer,
    VolunteerStatus,
    set_need_status,
)
from app.security import (
    STAFF_COOKIE_NAME,
    MFA_CHALLENGE_TTL_SECONDS,
    STAFF_SESSION_TTL_SECONDS,
    enforce_login_rate_limit,
    enforce_rate_limit,
    add_audit_event,
    add_record_history,
    matching_totp_counter,
    new_totp_secret,
    now_utc,
    permission_required,
    require_csrf,
    role_has_permission,
    secure_cookies,
)
from app.templatesconfig import templates
from app.manage_staff import hash_password, verify_password
from app.utils.pdfexports import generate_beneficiaries_pdf

router = APIRouter(
    dependencies=[Depends(require_csrf), Depends(enforce_login_rate_limit)]
)
protected_router = APIRouter()
DUMMY_PASSWORD_HASH = hash_password("invalid staff account password")


def _session_digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def get_staff_user(request: Request, session: Session) -> Optional[User]:
    token = request.cookies.get(STAFF_COOKIE_NAME)
    if not token:
        return None

    active_session = session.exec(
        select(AuthSession).where(AuthSession.token_hash == _session_digest(token))
    ).first()
    if not active_session:
        return None
    expires_at = active_session.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at <= now_utc():
        return None

    user = session.get(User, active_session.user_id)
    if (
        not user
        or not user.is_active
        or user.role == UserRole.USER
    ):
        return None
    return user


async def require_staff(request: Request, session: Session = Depends(get_session)) -> User:
    user = get_staff_user(request, session)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Staff sign-in required."
        )
    request.state.staff_user = user
    return user


async def require_admin(request: Request, session: Session = Depends(get_session)) -> User:
    user = await require_staff(request, session)
    if user.role != UserRole.ADMINISTRATOR:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Administrator role required.",
        )
    return user


def verify_staff_session(request: Request) -> bool:
    return isinstance(getattr(request.state, "staff_user", None), User)


def get_pending_auth_session(request: Request, session: Session) -> Optional[AuthSession]:
    token = request.cookies.get(STAFF_COOKIE_NAME)
    if not token:
        return None
    pending = session.exec(
        select(AuthSession).where(AuthSession.token_hash == _session_digest(token))
    ).first()
    if not pending or pending.mfa_verified:
        return None
    expires_at = pending.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    user = session.get(User, pending.user_id)
    if expires_at <= now_utc() or not user or not user.is_active:
        return None
    return pending


@router.get("/login", response_class=HTMLResponse)
async def get_admin_login(request: Request, session: Session = Depends(get_session)):
    if get_staff_user(request, session):
        return RedirectResponse(url="/admin/dashboard", status_code=303)
    return templates.TemplateResponse(
        request=request,
        name="adminlogin.html",
        context={"active_page": "admin"},
    )


@router.post("/login", response_class=HTMLResponse)
async def post_admin_login(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    session: Session = Depends(get_session),
):
    normalized_email = email.strip().lower()
    user = session.exec(select(User).where(User.email == normalized_email)).first()
    password_valid = verify_password(
        password, user.hashed_password if user else DUMMY_PASSWORD_HASH
    )
    if (
        not user
        or not user.is_active
        or user.role == UserRole.USER
        or not password_valid
    ):
        session.add(
            AuditLog(
                actor_identity=user.email if user else "unknown",
                action="auth.login_failed",
                target_type="user" if user else "authentication",
                target_id=str(user.id) if user else None,
            )
        )
        session.commit()
        return templates.TemplateResponse(
            request=request,
            name="adminlogin.html",
            status_code=status.HTTP_401_UNAUTHORIZED,
            context={
                "active_page": "admin",
                "error": "Invalid email or password.",
            },
        )

    token = secrets.token_urlsafe(32)
    session.add(
        AuthSession(
            token_hash=_session_digest(token),
            user_id=user.id,
            expires_at=now_utc() + timedelta(seconds=STAFF_SESSION_TTL_SECONDS),
            mfa_verified=True,
            mfa_setup_secret=None,
        )
    )
    session.commit()

    response = RedirectResponse(url="/admin/dashboard", status_code=303)
    response.set_cookie(
        key=STAFF_COOKIE_NAME,
        value=token,
        max_age=MFA_CHALLENGE_TTL_SECONDS,
        httponly=True,
        secure=secure_cookies(),
        samesite="lax",
        path="/",
    )
    return response


@router.get("/mfa", response_class=HTMLResponse)
async def get_mfa_setup(request: Request, session: Session = Depends(get_session)):
    if get_staff_user(request, session):
        return RedirectResponse(url="/admin/dashboard", status_code=303)
    return RedirectResponse(url="/admin/login", status_code=303)


@router.post("/mfa/verify")
async def verify_mfa(
    request: Request,
    code: str = Form(...),
    session: Session = Depends(get_session),
):
    if get_staff_user(request, session):
        return RedirectResponse(url="/admin/dashboard", status_code=303)
    return RedirectResponse(url="/admin/login", status_code=303)


@router.post("/mfa/cancel")
async def cancel_mfa(
    request: Request,
    session: Session = Depends(get_session),
):
    response = RedirectResponse(url="/admin/login", status_code=303)
    response.delete_cookie(
        key=STAFF_COOKIE_NAME,
        secure=secure_cookies(),
        httponly=True,
        samesite="lax",
        path="/",
    )
    return response


@router.post("/logout", dependencies=[Depends(require_staff)])
async def admin_logout(
    request: Request,
    session: Session = Depends(get_session),
):
    token = request.cookies.get(STAFF_COOKIE_NAME)
    if token:
        active_session = session.exec(
            select(AuthSession).where(AuthSession.token_hash == _session_digest(token))
        ).first()
        if active_session:
            add_audit_event(session, request, "auth.logout", "user", active_session.user_id)
            session.delete(active_session)
            session.commit()
    response = RedirectResponse(url="/admin/login", status_code=303)
    response.delete_cookie(
        key=STAFF_COOKIE_NAME,
        secure=secure_cookies(),
        httponly=True,
        samesite="lax",
        path="/",
    )
    return response


@protected_router.get("/dashboard", response_class=HTMLResponse)
async def get_admin_dashboard(
    request: Request,
    session: Session = Depends(get_session),
    staff_user: User = Depends(permission_required("dashboard")),
):
    from decimal import Decimal
    from typing import Dict

    from sqlmodel import col

    from app.models.entities import Donation, NewsArticle

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
    can_view_news = role_has_permission(staff_user.role, "news.read")
    can_view_reports = role_has_permission(staff_user.role, "reports.read")
    include_archived = (
        request.query_params.get("include_archived", "").lower() == "true"
    )

    volunteers = (
        session.exec(
            select(Volunteer)
            .where(
                True if include_archived else Volunteer.archived_at.is_(None)
            )
            .order_by(Volunteer.id.desc())
        ).all()
        if can_view_volunteers
        else []
    )
    donation_activity = (
        session.exec(select(Donation).order_by(col(Donation.id).desc())).all()
        if can_view_donations
        else []
    )
    donations = [
        donation
        for donation in donation_activity
        if include_archived or donation.archived_at is None
    ]
    if can_view_beneficiaries:
        all_needs = session.exec(
            select(BeneficiaryNeed).where(
                True if include_archived else BeneficiaryNeed.archived_at.is_(None)
            )
        ).all()
    elif can_view_needs:
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
                BeneficiaryNeed.created_at,
            ).where(
                BeneficiaryNeed.is_community_need.is_(True),
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
                created_at=row[9],
            )
            for row in need_rows
        ]
    else:
        all_needs = []
    news_articles = (
        session.exec(select(NewsArticle)).all() if can_view_news else []
    )

    beneficiaries = [
        need for need in all_needs if not need.is_community_need
    ]
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
    volunteer_onboarding = request.query_params.get(
        "volunteer_onboarding", ""
    ).strip()
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
                Donation.is_verified.is_(True),
                Donation.status != DonationStatus.REFUNDED.value,
                Donation.donation_type == "monetary",
                donation_date >= date_from.isoformat(),
                donation_date <= date_to.isoformat(),
            )
        ).one()
        request_date = func.date(BeneficiaryNeed.created_at)
        total_requests = session.exec(
            select(func.count(BeneficiaryNeed.id)).where(
                BeneficiaryNeed.is_community_need.is_(False),
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
    funding_need_ids = [
        need.id for need in community_needs if need.id is not None
    ]
    if can_view_donations and funding_need_ids:
        funding_rows = session.exec(
            select(
                DonationAllocation.need_id,
                func.sum(DonationAllocation.amount),
            )
            .join(Donation, Donation.id == DonationAllocation.donation_id)
            .where(
                DonationAllocation.need_id.in_(funding_need_ids),
                Donation.is_verified.is_(True),
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
            "volunteers": volunteers,
            "filtered_volunteers": filtered_volunteers,
            "donations": donations,
            "needs": community_needs,
            "allocation_needs": allocation_needs,
            "beneficiaries": filtered_beneficiaries,
            "news_articles": news_articles,
            "staff_user": request.state.staff_user,
            "can_view_volunteers": can_view_volunteers,
            "can_view_donations": can_view_donations,
            "can_view_beneficiaries": can_view_beneficiaries,
            "can_view_needs": can_view_needs,
            "can_view_news": can_view_news,
            "can_view_reports": can_view_reports,
            "can_write_needs": role_has_permission(staff_user.role, "needs.write"),
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


@protected_router.post("/needs/{need_id}/update-status")
async def update_need_status(
    need_id: int,
    request: Request,
    status_value: NeedStatus = Form(..., alias="status"),
    session: Session = Depends(get_session),
    staff_user: User = Depends(permission_required("beneficiaries.write")),
):
    need = session.get(BeneficiaryNeed, need_id)
    if not need or need.archived_at is not None:
        raise HTTPException(status_code=404, detail="Need record not found")
    form = await request.form()
    reason = str(form.get("reason", "")).strip()
    if (
        status_value in {NeedStatus.FULFILLED, NeedStatus.REJECTED}
        and not reason
    ):
        raise HTTPException(
            status_code=400,
            detail="A reason is required when closing or rejecting a request.",
        )
    previous_status = getattr(need.status, "value", need.status)
    set_need_status(need, status_value)
    session.add(need)
    add_record_history(
        session,
        request,
        "beneficiary_need",
        need_id,
        "status_changed",
        {
            "from": previous_status,
            "to": status_value.value,
            "reason": reason or None,
        },
    )
    add_audit_event(session, request, "beneficiary.status_changed", "beneficiary_need", need_id)
    session.commit()
    return RedirectResponse(url=f"/admin/beneficiaries/{need_id}", status_code=303)


@protected_router.get(
    "/beneficiaries/{need_id}",
    response_class=HTMLResponse,
    dependencies=[Depends(permission_required("beneficiaries.read"))],
)
async def get_beneficiary_detail(
    need_id: int,
    request: Request,
    session: Session = Depends(get_session),
):
    need = session.get(BeneficiaryNeed, need_id)
    if not need or need.is_community_need or need.archived_at is not None:
        raise HTTPException(status_code=404, detail="Assistance request not found.")
    add_audit_event(
        session, request, "beneficiary.detail_view", "beneficiary_need", need_id
    )
    session.commit()
    history = session.exec(
        select(RecordHistory)
        .where(
            RecordHistory.record_type == "beneficiary_need",
            RecordHistory.record_id == need_id,
        )
        .order_by(RecordHistory.occurred_at.desc())
    ).all()
    staff = session.exec(
        select(User)
        .where(
            User.is_active.is_(True),
            User.role.in_([UserRole.ADMINISTRATOR, UserRole.CASE_WORKER]),
        )
        .order_by(User.full_name)
    ).all()
    assigned_staff = (
        session.get(User, need.assigned_staff_id) if need.assigned_staff_id else None
    )
    return templates.TemplateResponse(
        request=request,
        name="adminbeneficiary.html",
        context={
            "active_page": "admin",
            "staff_user": request.state.staff_user,
            "need": need,
            "history": history,
            "staff_accounts": staff,
            "assigned_staff": assigned_staff,
            "need_statuses": list(NeedStatus),
        },
    )


@protected_router.post(
    "/beneficiaries/{need_id}/notes",
    dependencies=[Depends(permission_required("beneficiaries.write"))],
)
async def update_beneficiary_notes(
    need_id: int,
    request: Request,
    internal_notes: str = Form(...),
    session: Session = Depends(get_session),
):
    need = session.get(BeneficiaryNeed, need_id)
    if not need or need.is_community_need or need.archived_at is not None:
        raise HTTPException(status_code=404, detail="Assistance request not found.")
    notes = internal_notes.strip()
    if not notes or len(notes) > 4000:
        raise HTTPException(status_code=400, detail="Notes must be 1-4000 characters.")
    need.internal_notes = notes
    session.add(need)
    add_record_history(
        session, request, "beneficiary_need", need_id, "internal_note_added"
    )
    add_audit_event(session, request, "beneficiary.note_added", "beneficiary_need", need_id)
    session.commit()
    return RedirectResponse(url=f"/admin/beneficiaries/{need_id}", status_code=303)


@protected_router.post(
    "/beneficiaries/{need_id}/assign",
    dependencies=[Depends(permission_required("beneficiaries.write"))],
)
async def assign_beneficiary_request(
    need_id: int,
    request: Request,
    staff_id: str = Form(""),
    session: Session = Depends(get_session),
):
    need = session.get(BeneficiaryNeed, need_id)
    if not need or need.is_community_need or need.archived_at is not None:
        raise HTTPException(status_code=404, detail="Assistance request not found.")
    assigned_id = None
    if staff_id.strip():
        if not staff_id.isdigit():
            raise HTTPException(status_code=400, detail="Invalid staff selection.")
        assigned_id = int(staff_id)
        assignee = session.get(User, assigned_id)
        if (
            not assignee
            or not assignee.is_active
            or assignee.role not in {UserRole.ADMINISTRATOR, UserRole.CASE_WORKER}
        ):
            raise HTTPException(status_code=400, detail="Staff member is not eligible.")
    need.assigned_staff_id = assigned_id
    session.add(need)
    add_record_history(
        session,
        request,
        "beneficiary_need",
        need_id,
        "staff_assigned",
        {"staff_id": assigned_id},
    )
    add_audit_event(
        session, request, "beneficiary.staff_assigned", "beneficiary_need", need_id
    )
    session.commit()
    return RedirectResponse(url=f"/admin/beneficiaries/{need_id}", status_code=303)


@protected_router.post(
    "/beneficiaries/{need_id}/follow-up",
    dependencies=[Depends(permission_required("beneficiaries.write"))],
)
async def schedule_beneficiary_followup(
    need_id: int,
    request: Request,
    follow_up_at: str = Form(""),
    session: Session = Depends(get_session),
):
    need = session.get(BeneficiaryNeed, need_id)
    if not need or need.is_community_need or need.archived_at is not None:
        raise HTTPException(status_code=404, detail="Assistance request not found.")
    try:
        parsed = datetime.fromisoformat(follow_up_at) if follow_up_at else None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid follow-up date.") from exc
    if parsed and parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    need.follow_up_at = parsed
    session.add(need)
    add_record_history(
        session,
        request,
        "beneficiary_need",
        need_id,
        "follow_up_scheduled",
        {"follow_up_at": parsed.isoformat() if parsed else None},
    )
    add_audit_event(
        session, request, "beneficiary.follow_up_scheduled", "beneficiary_need", need_id
    )
    session.commit()
    return RedirectResponse(url=f"/admin/beneficiaries/{need_id}", status_code=303)


@protected_router.post("/volunteers/{volunteer_id}/assign-day")
async def assign_volunteer_day(
    volunteer_id: int,
    request: Request,
    assigned_day: str = Form(...),
    next_assignment_at: str = Form(""),
    session: Session = Depends(get_session),
    staff_user: User = Depends(permission_required("volunteers.write")),
):
    volunteer = session.get(Volunteer, volunteer_id)
    if not volunteer or volunteer.archived_at is not None:
        raise HTTPException(status_code=404, detail="Volunteer not found")
    valid_days = {
        "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"
    }
    if assigned_day not in valid_days | {"Inactive"}:
        raise HTTPException(status_code=400, detail="Invalid assigned day.")
    if (
        volunteer.available_days
        and assigned_day not in set(volunteer.available_days) | {"Inactive"}
    ):
        raise HTTPException(status_code=400, detail="Day is not in the volunteer's availability.")
    try:
        scheduled_at = (
            datetime.fromisoformat(next_assignment_at)
            if next_assignment_at.strip()
            else None
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid assignment date.") from exc
    if scheduled_at and scheduled_at.tzinfo is None:
        scheduled_at = scheduled_at.replace(tzinfo=timezone.utc)
    if scheduled_at and scheduled_at <= now_utc():
        raise HTTPException(
            status_code=400, detail="The next assignment date must be in the future."
        )
    if assigned_day == "Inactive" and scheduled_at:
        raise HTTPException(
            status_code=400,
            detail="An inactive volunteer cannot have a scheduled assignment.",
        )
    volunteer.assigned_day = assigned_day
    volunteer.next_assignment_at = scheduled_at
    volunteer.status = (
        VolunteerStatus.ASSIGNED
        if assigned_day != "Inactive"
        else VolunteerStatus.ACTIVE
    )
    session.add(volunteer)
    add_record_history(
        session,
        request,
        "volunteer",
        volunteer_id,
        "assignment_updated",
        {
            "assigned_day": assigned_day,
            "next_assignment_at": scheduled_at.isoformat() if scheduled_at else None,
        },
    )
    add_audit_event(
        session,
        request,
        "volunteer.day_assigned",
        "volunteer",
        volunteer_id,
        {"assigned_day": assigned_day},
    )
    session.commit()
    return RedirectResponse(
        url="/admin/dashboard#volunteers", status_code=status.HTTP_303_SEE_OTHER
    )


@protected_router.post(
    "/volunteers/{volunteer_id}/onboarding",
    dependencies=[Depends(permission_required("volunteers.write"))],
)
async def update_volunteer_onboarding(
    volunteer_id: int,
    request: Request,
    onboarding_status: str = Form(...),
    session: Session = Depends(get_session),
):
    volunteer = session.get(Volunteer, volunteer_id)
    if not volunteer or volunteer.archived_at is not None:
        raise HTTPException(status_code=404, detail="Volunteer not found.")
    allowed_statuses = {"Pending", "Contacted", "Approved", "Complete"}
    if onboarding_status not in allowed_statuses:
        raise HTTPException(status_code=400, detail="Invalid onboarding status.")
    old_status = volunteer.onboarding_status
    volunteer.onboarding_status = onboarding_status
    session.add(volunteer)
    add_record_history(
        session,
        request,
        "volunteer",
        volunteer_id,
        "onboarding_status_changed",
        {"from": old_status, "to": onboarding_status},
    )
    add_audit_event(
        session, request, "volunteer.onboarding_updated", "volunteer", volunteer_id
    )
    session.commit()
    return RedirectResponse(url="/admin/dashboard?tab=volunteers", status_code=303)


@protected_router.post(
    "/volunteers/{volunteer_id}/archive",
    dependencies=[Depends(permission_required("volunteers.write"))],
)
async def archive_volunteer(
    volunteer_id: int,
    request: Request,
    session: Session = Depends(get_session),
):
    volunteer = session.get(Volunteer, volunteer_id)
    if not volunteer or volunteer.archived_at is not None:
        raise HTTPException(status_code=404, detail="Volunteer not found.")
    volunteer.archived_at = now_utc()
    session.add(volunteer)
    add_record_history(session, request, "volunteer", volunteer_id, "archived")
    add_audit_event(session, request, "volunteer.archived", "volunteer", volunteer_id)
    session.commit()
    return RedirectResponse(url="/admin/dashboard?tab=volunteers", status_code=303)


@protected_router.get(
    "/beneficiaries/export-pdf",
    dependencies=[Depends(permission_required("exports.beneficiaries"))],
)
async def export_beneficiaries_pdf(
    request: Request,
    session: Session = Depends(get_session),
):
    needs = session.exec(select(BeneficiaryNeed)).all()
    pdf_buffer = generate_beneficiaries_pdf(list(needs))
    add_audit_event(session, request, "export.beneficiaries", "beneficiary_need")
    session.commit()
    return StreamingResponse(
        pdf_buffer,
        media_type="application/pdf",
        headers={
            "Content-Disposition": 'attachment; filename="beneficiary_requests.pdf"',
            "Cache-Control": "no-store",
        },
    )


@protected_router.get(
    "/staff", dependencies=[Depends(permission_required("staff.manage"))]
)
async def list_staff(
    request: Request,
    session: Session = Depends(get_session),
):
    add_audit_event(session, request, "staff_accounts.view", "user")
    session.commit()
    staff = session.exec(select(User).where(User.role != UserRole.USER)).all()
    return [
        {
            "id": user.id,
            "full_name": user.full_name,
            "email": user.email,
            "role": user.role.value,
            "is_active": user.is_active,
            "mfa_enabled": bool(user.mfa_secret),
            "created_at": user.created_at.isoformat(),
        }
        for user in staff
    ]


@protected_router.get(
    "/security",
    response_class=HTMLResponse,
    dependencies=[Depends(permission_required("staff.manage"))],
)
async def staff_security_page(
    request: Request,
    session: Session = Depends(get_session),
):
    add_audit_event(session, request, "staff_accounts.view", "user")
    add_audit_event(session, request, "audit.view", "audit_log")
    session.commit()
    staff = session.exec(
        select(User).where(User.role != UserRole.USER).order_by(User.email)
    ).all()
    audit_entries = session.exec(
        select(AuditLog).order_by(AuditLog.id.desc()).limit(100)
    ).all()
    return templates.TemplateResponse(
        request=request,
        name="adminsecurity.html",
        context={
            "active_page": "admin",
            "staff_user": request.state.staff_user,
            "staff_accounts": staff,
            "audit_entries": audit_entries,
            "roles": [
                role for role in UserRole if role != UserRole.USER
            ],
            "csrf_token": request.state.csrf_token,
        },
    )


@protected_router.post(
    "/staff/{user_id}/role",
    dependencies=[Depends(permission_required("staff.manage"))],
)
async def change_staff_role(
    user_id: int,
    request: Request,
    role: str = Form(...),
    session: Session = Depends(get_session),
):
    target = session.get(User, user_id)
    if not target or target.role == UserRole.USER:
        raise HTTPException(status_code=404, detail="Staff account not found.")
    try:
        new_role = UserRole(role)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid staff role.") from exc
    if new_role == UserRole.USER:
        raise HTTPException(status_code=400, detail="Invalid staff role.")
    if (
        target.is_active
        and target.role == UserRole.ADMINISTRATOR
        and new_role != UserRole.ADMINISTRATOR
        and session.exec(
            select(func.count(User.id)).where(
                User.role == UserRole.ADMINISTRATOR,
                User.is_active.is_(True),
            )
        ).one()
        <= 1
    ):
        raise HTTPException(
            status_code=409,
            detail="The last active administrator cannot be demoted.",
        )
    target.role = new_role
    session.add(target)
    for auth_session in session.exec(
        select(AuthSession).where(AuthSession.user_id == user_id)
    ).all():
        session.delete(auth_session)
    add_audit_event(
        session,
        request,
        "staff.role_changed",
        "user",
        user_id,
        {"role": new_role.value},
    )
    session.commit()
    return RedirectResponse(url="/admin/security", status_code=303)


@protected_router.post(
    "/staff/{user_id}/revoke-sessions",
    dependencies=[Depends(permission_required("staff.manage"))],
)
async def revoke_staff_sessions(
    user_id: int,
    request: Request,
    session: Session = Depends(get_session),
):
    target = session.get(User, user_id)
    if not target or target.role == UserRole.USER:
        raise HTTPException(status_code=404, detail="Staff account not found.")
    sessions = session.exec(
        select(AuthSession).where(AuthSession.user_id == user_id)
    ).all()
    for auth_session in sessions:
        session.delete(auth_session)
    add_audit_event(
        session,
        request,
        "staff.sessions_revoked",
        "user",
        user_id,
        {"revoked_count": len(sessions)},
    )
    session.commit()
    return RedirectResponse(url="/admin/security", status_code=303)


@protected_router.post(
    "/staff/{user_id}/deactivate",
    dependencies=[Depends(permission_required("staff.manage"))],
)
async def deactivate_staff(
    user_id: int,
    request: Request,
    session: Session = Depends(get_session),
):
    target = session.get(User, user_id)
    if not target or target.role == UserRole.USER:
        raise HTTPException(status_code=404, detail="Staff account not found.")
    if (
        target.is_active
        and target.role == UserRole.ADMINISTRATOR
        and session.exec(
            select(func.count(User.id)).where(
                User.role == UserRole.ADMINISTRATOR,
                User.is_active.is_(True),
            )
        ).one()
        <= 1
    ):
        raise HTTPException(
            status_code=409,
            detail="The last active administrator cannot be deactivated.",
        )
    target.is_active = False
    session.add(target)
    sessions = session.exec(
        select(AuthSession).where(AuthSession.user_id == user_id)
    ).all()
    for auth_session in sessions:
        session.delete(auth_session)
    add_audit_event(session, request, "staff.deactivated", "user", user_id)
    session.commit()
    return RedirectResponse(url="/admin/security", status_code=303)


@protected_router.get(
    "/audit-log", dependencies=[Depends(permission_required("audit.read"))]
)
async def read_audit_log(
    request: Request,
    session: Session = Depends(get_session),
    limit: int = 100,
    offset: int = 0,
):
    if not 1 <= limit <= 500 or offset < 0:
        raise HTTPException(status_code=400, detail="Invalid audit log page.")
    add_audit_event(session, request, "audit.view", "audit_log")
    session.commit()
    entries = session.exec(
        select(AuditLog)
        .order_by(AuditLog.id.desc())
        .offset(offset)
        .limit(limit)
    ).all()
    return [
        {
            "id": entry.id,
            "actor_id": entry.actor_id,
            "actor_identity": entry.actor_identity,
            "action": entry.action,
            "target_type": entry.target_type,
            "target_id": entry.target_id,
            "occurred_at": entry.occurred_at.isoformat(),
            "details": entry.details,
        }
        for entry in entries
    ]
