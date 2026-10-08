import hashlib
import secrets
from datetime import date, timedelta, timezone
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
    NeedStatus,
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

    volunteers = (
        session.exec(select(Volunteer)).all() if can_view_volunteers else []
    )
    donations = (
        session.exec(select(Donation).order_by(col(Donation.id).desc())).all()
        if can_view_donations
        else []
    )
    if can_view_beneficiaries:
        all_needs = session.exec(select(BeneficiaryNeed)).all()
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
            ).where(BeneficiaryNeed.is_community_need.is_(True))
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

    def is_in_date_range(record) -> bool:
        created_at = record.created_at
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        return date_from <= created_at.date() <= date_to

    range_volunteers = [record for record in volunteers if is_in_date_range(record)]
    range_donations = [record for record in donations if is_in_date_range(record)]
    range_beneficiaries = [record for record in beneficiaries if is_in_date_range(record)]
    range_news_articles = [record for record in news_articles if is_in_date_range(record)]

    total_donation_amount = sum(
        (
            donation.amount
            for donation in range_donations
            if donation.amount
            and donation.is_verified
            and donation.donation_type == "monetary"
        ),
        Decimal("0.00"),
    )
    if staff_user.role == UserRole.READ_ONLY:
        date_filter = func.date(Volunteer.created_at)
        total_volunteers = session.exec(
            select(func.count(Volunteer.id)).where(
                date_filter >= date_from.isoformat(),
                date_filter <= date_to.isoformat(),
            )
        ).one()
        donation_date = func.date(Donation.created_at)
        total_donation_amount = session.exec(
            select(func.coalesce(func.sum(Donation.amount), 0)).where(
                Donation.is_verified.is_(True),
                Donation.donation_type == "monetary",
                donation_date >= date_from.isoformat(),
                donation_date <= date_to.isoformat(),
            )
        ).one()
        request_date = func.date(BeneficiaryNeed.created_at)
        total_requests = session.exec(
            select(func.count(BeneficiaryNeed.id)).where(
                BeneficiaryNeed.is_community_need.is_(False),
                request_date >= date_from.isoformat(),
                request_date <= date_to.isoformat(),
            )
        ).one()
        news_date = func.date(NewsArticle.created_at)
        total_news = session.exec(
            select(func.count(NewsArticle.id)).where(
                news_date >= date_from.isoformat(),
                news_date <= date_to.isoformat(),
            )
        ).one()
    else:
        total_volunteers = len(range_volunteers)
        total_requests = len(range_beneficiaries)
        total_news = len(range_news_articles)
    need_funding_progress: Dict[int, Dict[str, Decimal]] = {}
    for need in all_needs:
        if need.id is None:
            continue
        allocated = [
            donation
            for donation in donations
            if donation.need_id == need.id and donation.is_verified
        ]
        raised = sum(
            (donation.allocated_amount or Decimal("0.00") for donation in allocated),
            Decimal("0.00"),
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
                        and donation.donation_type == "monetary"
                        and donation.created_at.strftime("%Y-%m")
                        == month.strftime("%Y-%m")
                    ),
                    Decimal("0.00"),
                )
            )
        )

    pending_donations = sum(not donation.is_verified for donation in donations)
    pending_beneficiaries = sum(
        need.status == NeedStatus.PENDING for need in beneficiaries
    )
    pending_needs = sum(
        need.status == NeedStatus.PENDING for need in community_needs
    )

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
            "donations": donations,
            "needs": community_needs,
            "beneficiaries": beneficiaries,
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
            "chart_month_labels": chart_month_labels,
            "monthly_volunteer_counts": monthly_volunteer_counts,
            "monthly_verified_donations": monthly_verified_donations,
            "has_volunteer_activity": bool(range_volunteers),
            "has_verified_donation_activity": any(
                donation.is_verified
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
                    pending_donations if can_view_donations else 0,
                    pending_beneficiaries if can_view_beneficiaries else 0,
                    pending_needs if can_view_needs else 0,
                )
            ),
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
    if not need:
        raise HTTPException(status_code=404, detail="Need record not found")
    set_need_status(need, status_value)
    session.add(need)
    add_audit_event(session, request, "beneficiary.status_changed", "beneficiary_need", need_id)
    session.commit()
    return RedirectResponse(url="/admin/dashboard#beneficiaries", status_code=303)


@protected_router.post("/volunteers/{volunteer_id}/assign-day")
async def assign_volunteer_day(
    volunteer_id: int,
    request: Request,
    assigned_day: str = Form(...),
    session: Session = Depends(get_session),
    staff_user: User = Depends(permission_required("volunteers.write")),
):
    volunteer = session.get(Volunteer, volunteer_id)
    if not volunteer:
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
    volunteer.assigned_day = assigned_day
    volunteer.status = (
        VolunteerStatus.ASSIGNED
        if assigned_day != "Inactive"
        else VolunteerStatus.ACTIVE
    )
    session.add(volunteer)
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
