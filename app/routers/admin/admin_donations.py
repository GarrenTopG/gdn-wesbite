from decimal import Decimal
from typing import Optional
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlmodel import Session, select

from app.db.session import get_session
from app.models.entities import BeneficiaryNeed, Donation, NeedStatus
from app.templates_config import templates
from app.routers.admin.auth import verify_admin_session

router = APIRouter()


def recalculate_need_status(session: Session, need_id: int) -> None:
    """
    Recalculates total allocated donations for a specific BeneficiaryNeed,
    updates its current_amount, and updates status accordingly.
    """
    need = session.get(BeneficiaryNeed, need_id)
    if not need:
        return

    donations = session.exec(
        select(Donation).where(Donation.need_id == need_id)
    ).all()

    total_raised = sum((d.allocated_amount or Decimal("0.00") for d in donations), Decimal("0.00"))
    need.current_amount = total_raised

    if need.target_amount and need.target_amount > Decimal("0.00"):
        if need.current_amount >= need.target_amount:
            need.status = NeedStatus.FULFILLED
        elif need.current_amount > Decimal("0.00") and need.status == NeedStatus.PENDING:
            need.status = NeedStatus.IN_PROGRESS

    session.add(need)
    session.commit()


@router.post("/donations/{donation_id}/verify")
async def verify_donation(
    donation_id: int,
    request: Request,
    session: Session = Depends(get_session),
):
    if not verify_admin_session(request):
        raise HTTPException(status_code=401, detail="Unauthorized")

    donation = session.get(Donation, donation_id)
    if not donation:
        raise HTTPException(status_code=404, detail="Donation record not found")

    donation.is_verified = True
    session.add(donation)
    session.commit()

    if request.headers.get("HX-Request"):
        return templates.TemplateResponse(
            request=request,
            name="partials/_donation_row.html",
            context={"donation": donation},
        )

    return RedirectResponse(url="/admin/dashboard?tab=donations", status_code=303)


@router.post("/donations/{donation_id}/allocate")
async def allocate_donation(
    donation_id: int,
    request: Request,
    need_id: int = Form(...),
    allocate_amount: Optional[str] = Form(None),
    amount: Optional[str] = Form(None),
    session: Session = Depends(get_session),
):
    if not verify_admin_session(request):
        raise HTTPException(status_code=401, detail="Unauthorized")

    donation = session.get(Donation, donation_id)
    if not donation:
        raise HTTPException(status_code=404, detail="Donation record not found")

    need = session.get(BeneficiaryNeed, need_id)
    if not need:
        raise HTTPException(status_code=404, detail="Community need not found")

    raw_amount = allocate_amount or amount
    if not raw_amount:
        raise HTTPException(status_code=400, detail="Allocation amount is required")

    try:
        alloc_decimal = Decimal(str(raw_amount).strip())
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid allocation amount format")

    total_amount = donation.amount or Decimal("0.00")
    current_allocated = donation.allocated_amount or Decimal("0.00")
    unallocated_balance = total_amount - current_allocated

    if alloc_decimal <= Decimal("0.00"):
        raise HTTPException(status_code=400, detail="Allocation amount must be greater than zero")

    if alloc_decimal > unallocated_balance:
        raise HTTPException(status_code=400, detail=f"Allocation R{alloc_decimal:.2f} exceeds remaining balance R{unallocated_balance:.2f}")

    donation.allocated_amount = current_allocated + alloc_decimal
    donation.is_verified = True
    donation.need_id = need_id

    session.add(donation)
    session.commit()

    recalculate_need_status(session, need_id)

    return RedirectResponse(url="/admin/dashboard?tab=donations", status_code=303)