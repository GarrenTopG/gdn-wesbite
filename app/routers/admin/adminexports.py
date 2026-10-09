import csv
from datetime import date
from io import StringIO
from types import SimpleNamespace

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlmodel import Session, select

from app.db.session import get_session
from app.models.entities import (
    BeneficiaryNeed,
    Donation,
    DonationAllocation,
    UserRole,
    Volunteer,
)
from app.routers.admin.auth import verify_staff_session
from app.utils.pdfexports import (
    generate_donations_pdf,
    generate_needs_pdf,
    generate_volunteers_pdf,
)

from app.security import add_audit_event, permission_required

router = APIRouter()

# Admin route to export BeneficiaryNeeds, Donations, and Volunteers as PDF reports
@router.get(
    "/volunteers/export-pdf",
    dependencies=[Depends(permission_required("exports.volunteers"))],
)
async def export_volunteers_pdf(
    request: Request,
    session: Session = Depends(get_session),
):
    if not verify_staff_session(request):
        raise HTTPException(status_code=401, detail="Unauthorized")

    volunteers = list(session.exec(select(Volunteer)).all())
    pdf_buffer = generate_volunteers_pdf(volunteers)
    add_audit_event(session, request, "export.volunteers", "volunteer")
    session.commit()

    return StreamingResponse(
        pdf_buffer,
        media_type="application/pdf",
        headers={"Content-Disposition": "attachment; filename=volunteers_report.pdf"},
    )

# Admin route to export BeneficiaryNeeds, Donations, and Volunteers as PDF reports
@router.get(
    "/donations/export-pdf",
    dependencies=[Depends(permission_required("exports.donations"))],
)
async def export_donations_pdf(
    request: Request,
    session: Session = Depends(get_session),
):
    if not verify_staff_session(request):
        raise HTTPException(status_code=401, detail="Unauthorized")

    donations = list(session.exec(select(Donation)).all())
    pdf_buffer = generate_donations_pdf(donations)
    add_audit_event(session, request, "export.donations", "donation")
    session.commit()

    return StreamingResponse(
        pdf_buffer,
        media_type="application/pdf",
        headers={"Content-Disposition": "attachment; filename=donations_ledger.pdf"},
    )


@router.get(
    "/donations/reconciliation.csv",
    dependencies=[Depends(permission_required("exports.donations"))],
)
async def export_donation_reconciliation_csv(
    request: Request,
    session: Session = Depends(get_session),
):
    def parse_date(key: str) -> date | None:
        raw = request.query_params.get(key)
        if not raw:
            return None
        try:
            parsed = date.fromisoformat(raw)
        except ValueError as exc:
            raise HTTPException(
                status_code=422,
                detail=f"{key} must use YYYY-MM-DD.",
            ) from exc
        if parsed.isoformat() != raw:
            raise HTTPException(
                status_code=422,
                detail=f"{key} must use YYYY-MM-DD.",
            )
        return parsed

    start = parse_date("from")
    end = parse_date("to")
    if start and end and start > end:
        raise HTTPException(status_code=422, detail="Start date must precede end date.")
    donations = session.exec(
        select(Donation)
        .order_by(Donation.created_at, Donation.id)
    ).all()
    filtered = [
        donation
        for donation in donations
        if (start is None or donation.created_at.date() >= start)
        and (end is None or donation.created_at.date() <= end)
    ]
    buffer = StringIO(newline="")
    writer = csv.writer(buffer)
    writer.writerow(
        [
            "donation_id",
            "submitted_at",
            "status",
            "donation_type",
            "amount_zar",
            "allocated_zar",
            "remaining_zar",
            "verified",
            "target_need_id",
            "allocated_need_ids",
        ]
    )
    donation_ids = [
        donation.id for donation in filtered if donation.id is not None
    ]
    allocated_need_ids: dict[int, set[int]] = {}
    if donation_ids:
        allocations = session.exec(
            select(DonationAllocation).where(
                DonationAllocation.donation_id.in_(donation_ids)
            )
        ).all()
        for allocation in allocations:
            allocated_need_ids.setdefault(allocation.donation_id, set()).add(
                allocation.need_id
            )
    for donation in filtered:
        amount = donation.amount or 0
        allocated = donation.allocated_amount or 0
        writer.writerow(
            [
                donation.id,
                donation.created_at.isoformat(),
                donation.status,
                donation.donation_type,
                f"{amount:.2f}",
                f"{allocated:.2f}",
                f"{amount - allocated:.2f}",
                "yes" if donation.is_verified else "no",
                donation.need_id or "",
                ";".join(
                    str(need_id)
                    for need_id in sorted(allocated_need_ids.get(donation.id, set()))
                ),
            ]
        )
    add_audit_event(
        session,
        request,
        "export.donation_reconciliation",
        "donation",
        details={
            "from": start.isoformat() if start else None,
            "to": end.isoformat() if end else None,
            "records": len(filtered),
        },
    )
    session.commit()
    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": 'attachment; filename="donation_reconciliation.csv"',
            "Cache-Control": "no-store",
        },
    )

# Admin route to export BeneficiaryNeeds as a PDF report
@router.get(
    "/needs/export-pdf",
    dependencies=[Depends(permission_required("exports.needs"))],
)
async def export_needs_pdf(
    request: Request,
    session: Session = Depends(get_session),
):
    if not verify_staff_session(request):
        raise HTTPException(status_code=401, detail="Unauthorized")

    if request.state.staff_user.role == UserRole.FINANCE:
        need_rows = session.exec(
            select(
                BeneficiaryNeed.id,
                BeneficiaryNeed.anonymised_title,
                BeneficiaryNeed.category,
                BeneficiaryNeed.area,
                BeneficiaryNeed.target_amount,
                BeneficiaryNeed.urgency,
                BeneficiaryNeed.status,
            ).where(BeneficiaryNeed.is_community_need.is_(True))
        ).all()
        needs = [
            SimpleNamespace(
                id=row[0],
                anonymised_title=row[1],
                category=row[2],
                area=row[3],
                target_amount=row[4],
                urgency=row[5],
                status=row[6],
            )
            for row in need_rows
        ]
    else:
        needs = list(session.exec(select(BeneficiaryNeed)).all())
    pdf_buffer = generate_needs_pdf(needs)
    add_audit_event(
        session,
        request,
        "export.needs",
        "community_need" if request.state.staff_user.role == UserRole.FINANCE else "beneficiary_need",
    )
    session.commit()

    return StreamingResponse(
        pdf_buffer,
        media_type="application/pdf",
        headers={"Content-Disposition": "attachment; filename=community_needs_report.pdf"},
    )