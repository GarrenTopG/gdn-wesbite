from datetime import timedelta
from decimal import Decimal, InvalidOperation
from typing import Optional
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import false, true, update
from sqlmodel import Session, select

from app.db.session import get_session
from app.models.entities import (
    BeneficiaryNeed,
    Campaign,
    Donation,
    DonationAllocation,
    DonationStatus,
    NeedStatus,
    ReceiptAccess,
    UserNotification,
    UserRole,
)
from app.templatesconfig import templates
from app.routers.admin.auth import verify_staff_session
from app.security import add_audit_event, add_record_history, permission_required
from app.security import now_utc
from app.services.campaigns import (
    notify_user,
    refresh_campaign_completion,
)

router = APIRouter(dependencies=[Depends(permission_required("donations.write"))])


def recalculate_need_funding(session: Session, need_id: int) -> None:
    need = session.get(BeneficiaryNeed, need_id)
    if not need:
        return

    allocated_amounts = session.exec(
        select(DonationAllocation.amount)
        .join(Donation, Donation.id == DonationAllocation.donation_id)
        .where(
            DonationAllocation.need_id == need_id,
            Donation.is_verified == true(),
            Donation.status != DonationStatus.REFUNDED.value,
        )
    ).all()
    direct_pledges = session.exec(
        select(Donation.amount).where(
            Donation.need_id == need_id,
            Donation.allocated_amount == Decimal("0.00"),
            Donation.is_verified == true(),
            Donation.status != DonationStatus.REFUNDED.value,
        )
    ).all()
    need.current_amount = sum(allocated_amounts, Decimal("0.00")) + sum(
        direct_pledges, Decimal("0.00")
    )
    session.add(need)


def record_need_funding_progress(
    session: Session, request: Request, need_id: int
) -> None:
    need = session.get(BeneficiaryNeed, need_id)
    if not need:
        return
    add_record_history(
        session,
        request,
        "beneficiary_need",
        need_id,
        "funding_progress_updated",
        {
            "current_amount": str(need.current_amount),
            "target_amount": str(need.target_amount),
            "status": getattr(need.status, "value", need.status),
        },
    )
    add_audit_event(
        session, request, "need.funding_progress_updated", "beneficiary_need", need_id
    )
    session.commit()


# Admin route to verify a donation
@router.post("/donations/{donation_id}/verify")
def verify_donation(
    donation_id: int,
    request: Request,
    session: Session = Depends(get_session),
):
    if not verify_staff_session(request):
        raise HTTPException(status_code=401, detail="Unauthorized")

    donation = session.get(Donation, donation_id)
    if not donation or donation.archived_at is not None:
        raise HTTPException(status_code=404, detail="Donation record not found")

    if donation.status == DonationStatus.REFUNDED.value:
        raise HTTPException(
            status_code=409, detail="A refunded donation cannot be verified."
        )
    if donation.status != DonationStatus.PAYMENT_PENDING.value:
        raise HTTPException(
            status_code=409, detail="Donation is not awaiting verification."
        )
    result = session.exec(
        update(Donation)
        .where(
            Donation.id == donation_id,
            Donation.archived_at.is_(None),
            Donation.is_verified == false(),
            Donation.status == DonationStatus.PAYMENT_PENDING.value,
        )
        .values(
            is_verified=True,
            status=DonationStatus.RECEIVED_VERIFIED.value,
        )
    )
    if result.rowcount != 1:
        raise HTTPException(
            status_code=409,
            detail="Contribution was already reviewed; refresh the donation queue.",
        )
    session.refresh(donation)
    add_record_history(
        session,
        request,
        "donation",
        donation_id,
        "status_changed",
        {"to": donation.status},
    )
    if donation.request_tax_certificate and donation.id is not None:
        if not donation.pending_receipt_token_hash:
            raise HTTPException(
                status_code=409,
                detail="Receipt access token is missing; a receipt cannot be issued.",
            )
        session.add(
            ReceiptAccess(
                donation_id=donation.id,
                token_hash=donation.pending_receipt_token_hash,
                expires_at=now_utc() + timedelta(days=30),
            )
        )
        donation.pending_receipt_token_hash = None
        session.add(donation)
        add_record_history(
            session,
            request,
            "donation",
            donation_id,
            "verified_tax_receipt_issued",
        )
    if donation.campaign_id is not None:
        campaign = session.get(Campaign, donation.campaign_id)
        if not campaign:
            raise HTTPException(
                status_code=409,
                detail="The linked campaign is unavailable; contribution was not verified.",
            )
        if donation.user_id is not None:
            notify_user(
                session,
                user_id=donation.user_id,
                campaign_id=campaign.id,
                donation_id=donation.id,
                event_type="contribution_verified",
                message=(
                    f"Your simulated contribution of R{donation.amount:.2f} to "
                    f"{campaign.title} has been approved and is now included in "
                    "verified demo progress. No real payment was processed."
                ),
            )
        refresh_campaign_completion(session, request, campaign)
    add_audit_event(session, request, "donation.verified", "donation", donation_id)
    if donation.need_id is not None:
        need = session.get(BeneficiaryNeed, donation.need_id)
        if not need or not need.is_community_need:
            raise HTTPException(
                status_code=409,
                detail="The linked community need is unavailable; pledge was not approved.",
            )
        if donation.user_id is not None:
            session.add(
                UserNotification(
                    user_id=donation.user_id,
                    donation_id=donation.id,
                    event_type="need_pledge_approved",
                    message=(
                        f"Your pledge of R{donation.amount:.2f} for "
                        f"{need.anonymised_title} was approved and is now included "
                        "in the community total."
                    ),
                )
            )
        recalculate_need_funding(session, need.id)
        record_need_funding_progress(session, request, need.id)
    session.commit()

    if request.headers.get("HX-Request"):
        return templates.TemplateResponse(
            request=request,
            name="partials/_donation_row.html",
            context={"donation": donation},
        )

    return RedirectResponse(url="/admin/dashboard?tab=donations", status_code=303)


# Admin route to allocate a donation to a specific BeneficiaryNeed
@router.post("/donations/{donation_id}/allocate")
def allocate_donation(
    donation_id: int,
    request: Request,
    need_id: int = Form(...),
    allocate_amount: Optional[str] = Form(None),
    amount: Optional[str] = Form(None),
    session: Session = Depends(get_session),
):
    if not verify_staff_session(request):
        raise HTTPException(status_code=401, detail="Unauthorized")

    donation = session.get(Donation, donation_id)
    if not donation or donation.archived_at is not None:
        raise HTTPException(status_code=404, detail="Donation record not found")
    if donation.need_id is not None:
        raise HTTPException(
            status_code=409,
            detail="A community pledge is already linked to its selected need.",
        )

    need = session.get(BeneficiaryNeed, need_id)
    if not need or need.archived_at is not None or need.status == NeedStatus.REJECTED:
        raise HTTPException(status_code=404, detail="Community need not found")
    if request.state.staff_user.role == UserRole.FINANCE and not need.is_community_need:
        raise HTTPException(status_code=404, detail="Community need not found")

    if not donation.is_verified or donation.status not in {
        DonationStatus.RECEIVED_VERIFIED.value,
        DonationStatus.ALLOCATED.value,
    }:
        raise HTTPException(
            status_code=409,
            detail="Only received and verified donations can be allocated.",
        )
    if donation.status == DonationStatus.ALLOCATED.value:
        raise HTTPException(
            status_code=409, detail="Donation is already fully allocated."
        )
    raw_amount = allocate_amount or amount
    if not raw_amount:
        raise HTTPException(status_code=400, detail="Allocation amount is required")

    try:
        alloc_decimal = Decimal(str(raw_amount).strip())
    except (InvalidOperation, ValueError):
        raise HTTPException(status_code=400, detail="Invalid allocation amount format")
    if not alloc_decimal.is_finite():
        raise HTTPException(status_code=400, detail="Allocation amount must be finite.")
    try:
        rounded_amount = alloc_decimal.quantize(Decimal("0.01"))
    except InvalidOperation as exc:
        raise HTTPException(
            status_code=400, detail="Invalid allocation precision."
        ) from exc
    if rounded_amount != alloc_decimal:
        raise HTTPException(
            status_code=400, detail="Allocation amounts may have at most two decimals."
        )

    total_amount = donation.amount or Decimal("0.00")
    current_allocated = donation.allocated_amount or Decimal("0.00")
    unallocated_balance = total_amount - current_allocated

    if alloc_decimal <= Decimal("0.00"):
        raise HTTPException(
            status_code=400, detail="Allocation amount must be greater than zero"
        )

    if alloc_decimal > unallocated_balance:
        raise HTTPException(
            status_code=400,
            detail=f"Allocation R{alloc_decimal:.2f} exceeds remaining balance R{unallocated_balance:.2f}",
        )
    remaining_need_target = (need.target_amount or Decimal("0.00")) - (
        need.current_amount or Decimal("0.00")
    )
    if need.target_amount > Decimal("0.00") and alloc_decimal > remaining_need_target:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Allocation R{alloc_decimal:.2f} exceeds remaining need target "
                f"R{max(remaining_need_target, Decimal('0.00')):.2f}."
            ),
        )

    new_total_allocated = current_allocated + alloc_decimal
    allocation = session.exec(
        select(DonationAllocation).where(
            DonationAllocation.donation_id == donation_id,
            DonationAllocation.need_id == need_id,
        )
    ).first()
    if allocation:
        allocation.amount += alloc_decimal
        session.add(allocation)
    else:
        session.add(
            DonationAllocation(
                donation_id=donation_id,
                need_id=need_id,
                amount=alloc_decimal,
            )
        )
    donation.allocated_amount = new_total_allocated
    if new_total_allocated >= total_amount:
        donation.status = DonationStatus.ALLOCATED.value

    session.add(donation)
    add_record_history(
        session,
        request,
        "donation",
        donation_id,
        "allocated",
        {
            "need_id": need_id,
            "amount": str(alloc_decimal),
            "allocated_total": str(new_total_allocated),
            "status": donation.status,
        },
    )
    add_audit_event(
        session,
        request,
        "donation.allocated",
        "donation",
        donation_id,
        {"need_id": need_id, "amount": str(alloc_decimal)},
    )
    session.commit()

    recalculate_need_funding(session, need_id)
    record_need_funding_progress(session, request, need_id)

    return RedirectResponse(url="/admin/dashboard?tab=donations", status_code=303)


@router.post("/donations/{donation_id}/status")
def update_donation_status(
    donation_id: int,
    request: Request,
    status: str = Form(...),
    session: Session = Depends(get_session),
):
    donation = session.get(Donation, donation_id)
    if not donation or donation.archived_at is not None:
        raise HTTPException(status_code=404, detail="Donation record not found.")
    if donation.need_id is not None:
        raise HTTPException(
            status_code=409,
            detail="Community pledges can only be approved or rejected.",
        )
    allowed_transitions = {
        DonationStatus.SUBMITTED.value: {
            DonationStatus.PAYMENT_PENDING.value,
            DonationStatus.REFUNDED.value,
        },
        DonationStatus.PAYMENT_PENDING.value: {DonationStatus.REFUNDED.value},
        DonationStatus.RECEIVED_VERIFIED.value: {DonationStatus.REFUNDED.value},
        DonationStatus.ALLOCATED.value: {DonationStatus.REFUNDED.value},
        DonationStatus.REFUNDED.value: set(),
    }
    if status not in allowed_transitions.get(donation.status, set()):
        raise HTTPException(
            status_code=409,
            detail=f"Invalid donation status transition from {donation.status}.",
        )
    old_status = donation.status
    if donation.campaign_id is not None:
        result = session.exec(
            update(Donation)
            .where(
                Donation.id == donation_id,
                Donation.archived_at.is_(None),
                Donation.status == old_status,
            )
            .values(
                status=status,
                is_verified=(
                    False
                    if status == DonationStatus.REFUNDED.value
                    else donation.is_verified
                ),
            )
        )
        if result.rowcount != 1:
            raise HTTPException(
                status_code=409,
                detail="Contribution status changed; refresh the donation queue.",
            )
        session.refresh(donation)
    else:
        donation.status = status
        if status == DonationStatus.REFUNDED.value:
            donation.is_verified = False
        session.add(donation)
    add_record_history(
        session,
        request,
        "donation",
        donation_id,
        "status_changed",
        {"from": old_status, "to": status},
    )
    add_audit_event(
        session,
        request,
        "donation.status_changed",
        "donation",
        donation_id,
        {"from": old_status, "to": status},
    )
    if status == DonationStatus.REFUNDED.value and donation.campaign_id is not None:
        campaign = session.get(Campaign, donation.campaign_id)
        if not campaign:
            raise HTTPException(status_code=409, detail="Campaign not found.")
        was_verified = old_status in {
            DonationStatus.RECEIVED_VERIFIED.value,
            DonationStatus.ALLOCATED.value,
        }
        if donation.user_id is not None:
            notify_user(
                session,
                user_id=donation.user_id,
                campaign_id=campaign.id,
                donation_id=donation.id,
                event_type=(
                    "contribution_refunded"
                    if was_verified
                    else "contribution_cancelled"
                ),
                message=(
                    f"Your simulated contribution of R{donation.amount:.2f} to "
                    f"{campaign.title} "
                    + (
                        "was removed from verified demo progress."
                        if was_verified
                        else "was cancelled and has not been included in progress."
                    )
                ),
            )
        refresh_campaign_completion(session, request, campaign)
    session.commit()
    if status == DonationStatus.REFUNDED.value:
        affected_need_ids = session.exec(
            select(DonationAllocation.need_id).where(
                DonationAllocation.donation_id == donation_id
            )
        ).all()
        for affected_need_id in set(affected_need_ids):
            recalculate_need_funding(session, affected_need_id)
            record_need_funding_progress(session, request, affected_need_id)
    return RedirectResponse(url="/admin/dashboard?tab=donations", status_code=303)


@router.post("/donations/{donation_id}/reject")
def reject_simulated_contribution(
    donation_id: int,
    request: Request,
    reason: str = Form(""),
    session: Session = Depends(get_session),
):
    if not verify_staff_session(request):
        raise HTTPException(status_code=401, detail="Unauthorized")
    donation = session.get(Donation, donation_id)
    if (
        not donation
        or donation.archived_at is not None
        or (donation.campaign_id is None and donation.need_id is None)
    ):
        raise HTTPException(status_code=404, detail="Contribution record not found.")
    if donation.status != DonationStatus.PAYMENT_PENDING.value:
        raise HTTPException(
            status_code=409, detail="Only pending contributions can be rejected."
        )
    campaign = (
        session.get(Campaign, donation.campaign_id)
        if donation.campaign_id is not None
        else None
    )
    need = (
        session.get(BeneficiaryNeed, donation.need_id)
        if donation.need_id is not None
        else None
    )
    if donation.campaign_id is not None and not campaign:
        raise HTTPException(status_code=409, detail="Campaign not found.")
    previous_status = donation.status
    result = session.exec(
        update(Donation)
        .where(
            Donation.id == donation_id,
            Donation.archived_at.is_(None),
            Donation.status == DonationStatus.PAYMENT_PENDING.value,
            Donation.is_verified == false(),
        )
        .values(
            status=DonationStatus.REJECTED.value,
            is_verified=False,
        )
    )
    if result.rowcount != 1:
        raise HTTPException(
            status_code=409,
            detail="Contribution was already reviewed; refresh the donation queue.",
        )
    session.refresh(donation)
    clean_reason = reason.strip()[:1000]
    add_record_history(
        session,
        request,
        "donation",
        donation_id,
        "simulated_contribution_rejected",
        {"reason": clean_reason or None},
    )
    add_audit_event(
        session,
        request,
        "donation.simulated_contribution_rejected",
        "donation",
        donation_id,
        {"from": previous_status, "reason": clean_reason or None},
    )
    if donation.user_id is not None and campaign is not None:
        notify_user(
            session,
            user_id=donation.user_id,
            campaign_id=campaign.id,
            donation_id=donation.id,
            event_type="contribution_rejected",
            message=(
                f"Your simulated contribution to {campaign.title} was not approved. "
                "It has not been included in campaign progress."
            ),
        )
    elif donation.user_id is not None and need is not None:
        session.add(
            UserNotification(
                user_id=donation.user_id,
                donation_id=donation.id,
                event_type="need_pledge_rejected",
                message=(
                    f"Your pledge of R{donation.amount:.2f} for "
                    f"{need.anonymised_title} was rejected and is not included "
                    "in the community total."
                ),
            )
        )
    session.commit()
    return RedirectResponse(url="/admin/dashboard?tab=donations", status_code=303)


@router.post("/donations/{donation_id}/archive")
def archive_donation(
    donation_id: int,
    request: Request,
    session: Session = Depends(get_session),
):
    donation = session.get(Donation, donation_id)
    if not donation or donation.archived_at is not None:
        raise HTTPException(status_code=404, detail="Donation record not found.")
    from app.security import now_utc

    donation.archived_at = now_utc()
    session.add(donation)
    add_record_history(session, request, "donation", donation_id, "archived")
    add_audit_event(session, request, "donation.archived", "donation", donation_id)
    session.commit()
    return RedirectResponse(url="/admin/dashboard?tab=donations", status_code=303)
