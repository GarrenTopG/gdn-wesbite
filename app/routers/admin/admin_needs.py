from decimal import Decimal
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
)
from app.routers.admin.auth import verify_admin_session

router = APIRouter()


@router.post("/needs/add")
async def create_community_need(
    request: Request,
    anonymised_title: str = Form(...),
    area: str = Form(...),
    category: str = Form(...),
    urgency: str = Form("Medium"),
    contact_name: str = Form("Admin Internal"),
    contact_phone: str = Form("+27 00 000 0000"),
    full_address: str = Form("Admin Direct Entry"),
    target_amount: str = Form("0.00"),
    session: Session = Depends(get_session),
):
    if not verify_admin_session(request):
        raise HTTPException(status_code=401, detail="Unauthorized")

    try:
        parsed_target = Decimal(target_amount)
    except Exception:
        parsed_target = Decimal("0.00")

    try:
        urgency_enum = NeedUrgency(urgency)
    except ValueError:
        try:
            urgency_enum = NeedUrgency(urgency.lower())
        except ValueError:
            try:
                urgency_enum = NeedUrgency(urgency.upper())
            except ValueError:
                urgency_enum = NeedUrgency.MEDIUM

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
    )
    session.add(new_need)
    session.commit()

    return RedirectResponse(url="/admin/dashboard?tab=needs", status_code=303)


@router.post("/needs/delete/{need_id}")
async def delete_community_need(
    need_id: int,
    request: Request,
    session: Session = Depends(get_session)
):
    if not verify_admin_session(request):
        raise HTTPException(status_code=401, detail="Unauthorized")
        
    need = session.get(BeneficiaryNeed, need_id)
    if need:
        session.delete(need)
        session.commit()
        
    return RedirectResponse(url="/admin/dashboard?tab=needs", status_code=303)


@router.post("/needs/{need_id}/status")
async def update_need_status(
    need_id: int,
    request: Request,
    status: str = Form(...),
    session: Session = Depends(get_session),
):
    if not verify_admin_session(request):
        raise HTTPException(status_code=401, detail="Unauthorized")

    need = session.get(BeneficiaryNeed, need_id)
    if not need:
        raise HTTPException(status_code=404, detail="Need record not found")

    try:
        need.status = NeedStatus(status)
    except ValueError:
        need.status = NeedStatus.PENDING

    session.add(need)
    session.commit()
    
    if request.headers.get("HX-Request"):
        return Response(status_code=200)

    return RedirectResponse(url="/admin/dashboard", status_code=303)


@router.post("/needs/{need_id}/assign-volunteer")
async def assign_volunteer_to_need(
    need_id: int,
    request: Request,
    volunteer_id: int = Form(...),
    session: Session = Depends(get_session),
):
    if not verify_admin_session(request):
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
    need.status = NeedStatus.IN_PROGRESS
    volunteer.status = VolunteerStatus.ASSIGNED

    session.add(match)
    session.add(need)
    session.add(volunteer)
    session.commit()

    if request.headers.get("HX-Request"):
        return Response(status_code=200)

    return RedirectResponse(url="/admin/dashboard", status_code=303)