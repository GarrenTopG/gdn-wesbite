from types import SimpleNamespace

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlmodel import Session, select

from app.db.session import get_session
from app.models.entities import BeneficiaryNeed, Donation, UserRole, Volunteer
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