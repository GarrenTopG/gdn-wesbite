from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import true
from sqlmodel import Session, func, select

from app.db.session import get_session
from app.models.entities import AuthSession, AuditLog, User, UserRole
from app.security import add_audit_event, permission_required
from app.templatesconfig import templates

router = APIRouter()


@router.get("/staff", dependencies=[Depends(permission_required("staff.manage"))])
def list_staff(
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


@router.get(
    "/security",
    response_class=HTMLResponse,
    dependencies=[Depends(permission_required("staff.manage"))],
)
def staff_security_page(
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
            "roles": [role for role in UserRole if role != UserRole.USER],
            "csrf_token": request.state.csrf_token,
        },
    )


@router.post(
    "/staff/{user_id}/role",
    dependencies=[Depends(permission_required("staff.manage"))],
)
def change_staff_role(
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
                User.is_active == true(),
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


@router.post(
    "/staff/{user_id}/revoke-sessions",
    dependencies=[Depends(permission_required("staff.manage"))],
)
def revoke_staff_sessions(
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


@router.post(
    "/staff/{user_id}/deactivate",
    dependencies=[Depends(permission_required("staff.manage"))],
)
def deactivate_staff(
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
                User.is_active == true(),
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


@router.get("/audit-log", dependencies=[Depends(permission_required("audit.read"))])
def read_audit_log(
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
        select(AuditLog).order_by(AuditLog.id.desc()).offset(offset).limit(limit)
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
