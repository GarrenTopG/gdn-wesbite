from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import true
from sqlmodel import Session, select
from starlette.datastructures import FormData

from app.db.session import get_session
from app.models.entities import (
    BeneficiaryNeed,
    NeedStatus,
    RecordHistory,
    StaffNotificationRead,
    User,
    UserRole,
    Volunteer,
    VolunteerStatus,
    set_need_status,
)
from app.routers.form_data import parse_form_data
from app.security import (
    add_audit_event,
    add_record_history,
    now_utc,
    permission_required,
    role_has_permission,
)
from app.templatesconfig import templates
from app.routers.admin.dashboard import NOTIFICATION_PERMISSIONS

router = APIRouter()


@router.post("/notifications/read")
def mark_notification_read(
    notification_key: str = Form(...),
    fingerprint: str = Form(...),
    session: Session = Depends(get_session),
    staff_user: User = Depends(permission_required("dashboard")),
):
    permission = NOTIFICATION_PERMISSIONS.get(notification_key)
    if not permission or not role_has_permission(staff_user.role, permission):
        raise HTTPException(status_code=403, detail="Notification is not available.")
    if len(fingerprint) != 64 or any(
        character not in "0123456789abcdef" for character in fingerprint
    ):
        raise HTTPException(status_code=422, detail="Invalid notification fingerprint.")

    notification_read = session.exec(
        select(StaffNotificationRead).where(
            StaffNotificationRead.staff_user_id == staff_user.id,
            StaffNotificationRead.notification_key == notification_key,
        )
    ).first()
    if notification_read:
        notification_read.fingerprint = fingerprint
        notification_read.updated_at = now_utc()
    else:
        notification_read = StaffNotificationRead(
            staff_user_id=staff_user.id,
            notification_key=notification_key,
            fingerprint=fingerprint,
            updated_at=now_utc(),
        )
        session.add(notification_read)
    session.commit()
    return {"ok": True}


@router.post("/needs/{need_id}/update-status")
def update_need_status(
    need_id: int,
    request: Request,
    status_value: NeedStatus = Form(..., alias="status"),
    form: FormData = Depends(parse_form_data),
    session: Session = Depends(get_session),
    staff_user: User = Depends(permission_required("beneficiaries.write")),
):
    need = session.get(BeneficiaryNeed, need_id)
    if not need or need.archived_at is not None:
        raise HTTPException(status_code=404, detail="Need record not found")
    reason = str(form.get("reason", "")).strip()
    if status_value in {NeedStatus.FULFILLED, NeedStatus.REJECTED} and not reason:
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
    add_audit_event(
        session, request, "beneficiary.status_changed", "beneficiary_need", need_id
    )
    session.commit()
    return RedirectResponse(url=f"/admin/beneficiaries/{need_id}", status_code=303)


@router.get(
    "/beneficiaries/{need_id:int}",
    response_class=HTMLResponse,
    dependencies=[Depends(permission_required("beneficiaries.read"))],
)
def get_beneficiary_detail(
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
            User.is_active == true(),
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


@router.post(
    "/beneficiaries/{need_id}/notes",
    dependencies=[Depends(permission_required("beneficiaries.write"))],
)
def update_beneficiary_notes(
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
    add_audit_event(
        session, request, "beneficiary.note_added", "beneficiary_need", need_id
    )
    session.commit()
    return RedirectResponse(url=f"/admin/beneficiaries/{need_id}", status_code=303)


@router.post(
    "/beneficiaries/{need_id}/assign",
    dependencies=[Depends(permission_required("beneficiaries.write"))],
)
def assign_beneficiary_request(
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


@router.post(
    "/beneficiaries/{need_id}/follow-up",
    dependencies=[Depends(permission_required("beneficiaries.write"))],
)
def schedule_beneficiary_followup(
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


@router.post("/volunteers/{volunteer_id}/assign-day")
def assign_volunteer_day(
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
        "Monday",
        "Tuesday",
        "Wednesday",
        "Thursday",
        "Friday",
        "Saturday",
        "Sunday",
    }
    if assigned_day not in valid_days | {"Inactive"}:
        raise HTTPException(status_code=400, detail="Invalid assigned day.")
    if volunteer.available_days and assigned_day not in set(
        volunteer.available_days
    ) | {"Inactive"}:
        raise HTTPException(
            status_code=400, detail="Day is not in the volunteer's availability."
        )
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


@router.post(
    "/volunteers/{volunteer_id}/onboarding",
    dependencies=[Depends(permission_required("volunteers.write"))],
)
def update_volunteer_onboarding(
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


@router.post(
    "/volunteers/{volunteer_id}/archive",
    dependencies=[Depends(permission_required("volunteers.write"))],
)
def archive_volunteer(
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
