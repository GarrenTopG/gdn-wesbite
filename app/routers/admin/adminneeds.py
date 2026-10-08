from decimal import Decimal, InvalidOperation
from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from sqlmodel import Session

from app.db.session import get_session
from app.models.entities import (
    BeneficiaryNeed,
    NeedStatus,
    NeedUrgency,
    Volunteer,
    VolunteerMatch,
    VolunteerStatus,
    set_need_status,
)
from app.routers.admin.auth import verify_staff_session
from app.security import add_audit_event, permission_required

router = APIRouter(dependencies=[Depends(permission_required("needs.write"))])

# Admin route to create a new BeneficiaryNeed directly from the admin dashboard
@router.post("/needs/add")
async def create_community_need(
    request: Request,
    anonymised_title: str = Form(...),
    area: str = Form(...),
    category: str = Form(...),
    urgency: str = Form("Medium"),
    contact_name: str = Form(""),
    contact_phone: str = Form(""),
    full_address: str = Form(""),
    target_amount: str = Form("0.00"),
    session: Session = Depends(get_session),
):
    if not verify_staff_session(request):
        raise HTTPException(status_code=401, detail="Unauthorized")

    try:
        parsed_target = Decimal(target_amount)
    except (InvalidOperation, ValueError):
        raise HTTPException(status_code=400, detail="Invalid target amount.")
    if not parsed_target.is_finite() or parsed_target < Decimal("0.00"):
        raise HTTPException(status_code=400, detail="Target amount must be zero or greater.")

    try:
        urgency_enum = NeedUrgency(urgency)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid urgency value.")

    new_need = BeneficiaryNeed(
        contact_name=contact_name,
        contact_phone=contact_phone,
        full_address=full_address,
        anonymised_title=anonymised_title,
        area=area,
        category=category,
        urgency=urgency_enum,
        target_amount=parsed_target,
        status=NeedStatus.PENDING,
        is_community_need=True,
    )
    session.add(new_need)
    session.flush()
    add_audit_event(session, request, "need.created", "beneficiary_need", new_need.id)
    session.commit()

    return RedirectResponse(url="/admin/dashboard?tab=needs", status_code=303)

# Admin route to delete a BeneficiaryNeed from the admin dashboard
@router.post("/needs/delete/{need_id}")
async def delete_community_need(
    need_id: int,
    request: Request,
    session: Session = Depends(get_session)
):
    if not verify_staff_session(request):
        raise HTTPException(status_code=401, detail="Unauthorized")
        
    need = session.get(BeneficiaryNeed, need_id)
    if not need or not need.is_community_need:
        raise HTTPException(status_code=404, detail="Community need not found")
    add_audit_event(session, request, "need.deleted", "beneficiary_need", need_id)
    session.delete(need)
    session.commit()
        
    return RedirectResponse(url="/admin/dashboard?tab=needs", status_code=303)

# Admin route to update the status of a BeneficiaryNeed from the admin dashboard
@router.post("/needs/{need_id}/status")
async def update_need_status(
    need_id: int,
    request: Request,
    status: str = Form(...),
    session: Session = Depends(get_session),
):
    if not verify_staff_session(request):
        raise HTTPException(status_code=401, detail="Unauthorized")

    need = session.get(BeneficiaryNeed, need_id)
    if not need:
        raise HTTPException(status_code=404, detail="Need record not found")

    try:
        new_status = NeedStatus(status)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid need status.")
    set_need_status(need, new_status)

    session.add(need)
    add_audit_event(
        session,
        request,
        "need.status_changed",
        "beneficiary_need",
        need_id,
        {"status": new_status.value},
    )
    session.commit()
    
    if request.headers.get("HX-Request"):
        return Response(status_code=200)

    return RedirectResponse(url="/admin/dashboard", status_code=303)

# Admin route to assign a volunteer to a BeneficiaryNeed from the admin dashboard
@router.post("/needs/{need_id}/assign-volunteer")
async def assign_volunteer_to_need(
    need_id: int,
    request: Request,
    volunteer_id: int = Form(...),
    session: Session = Depends(get_session),
):
    if not verify_staff_session(request):
        raise HTTPException(status_code=401, detail="Unauthorized")

    need = session.get(BeneficiaryNeed, need_id)
    volunteer = session.get(Volunteer, volunteer_id)

    if not need or not volunteer:
        raise HTTPException(status_code=404, detail="Need or Volunteer record missing")

    assert need.id is not None
    assert volunteer.id is not None

    match = VolunteerMatch(
        need_id=need.id,
        volunteer_id=volunteer.id,
        matched_by_admin="Admin Direct Match",
    )
    set_need_status(need, NeedStatus.IN_PROGRESS)
    volunteer.status = VolunteerStatus.ASSIGNED

    session.add(match)
    session.add(need)
    session.add(volunteer)
    add_audit_event(
        session,
        request,
        "need.volunteer_assigned",
        "beneficiary_need",
        need_id,
        {"volunteer_id": volunteer_id},
    )
    session.commit()

    if request.headers.get("HX-Request"):
        return Response(status_code=200)

    return RedirectResponse(url="/admin/dashboard", status_code=303)