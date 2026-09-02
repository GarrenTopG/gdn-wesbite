from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlmodel import Session, select

from app.db.session import get_session
from app.models.entities import BeneficiaryNeed, Donation, Volunteer
from app.routers.admin.auth import verify_admin_session
from app.utils.pdf_exports import (
    generate_donations_pdf,
    generate_needs_pdf,
    generate_volunteers_pdf,
)

router = APIRouter()


@router.get("/volunteers/export-pdf")
async def export_volunteers_pdf(
    request: Request,
    session: Session = Depends(get_session),
):
    if not verify_admin_session(request):
        raise HTTPException(status_code=401, detail="Unauthorized")

    volunteers = list(session.exec(select(Volunteer)).all())
    pdf_buffer = generate_volunteers_pdf(volunteers)

    return StreamingResponse(
        pdf_buffer,
        media_type="application/pdf",
        headers={"Content-Disposition": "attachment; filename=volunteers_report.pdf"},
    )


@router.get("/donations/export-pdf")
async def export_donations_pdf(
    request: Request,
    session: Session = Depends(get_session),
):
    if not verify_admin_session(request):
        raise HTTPException(status_code=401, detail="Unauthorized")

    donations = list(session.exec(select(Donation)).all())
    pdf_buffer = generate_donations_pdf(donations)

    return StreamingResponse(
        pdf_buffer,
        media_type="application/pdf",
        headers={"Content-Disposition": "attachment; filename=donations_ledger.pdf"},
    )


@router.get("/needs/export-pdf")
async def export_needs_pdf(
    request: Request,
    session: Session = Depends(get_session),
):
    if not verify_admin_session(request):
        raise HTTPException(status_code=401, detail="Unauthorized")

    needs = list(session.exec(select(BeneficiaryNeed)).all())
    pdf_buffer = generate_needs_pdf(needs)

    return StreamingResponse(
        pdf_buffer,
        media_type="application/pdf",
        headers={"Content-Disposition": "attachment; filename=community_needs_report.pdf"},
    )