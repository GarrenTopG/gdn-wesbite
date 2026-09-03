import re
from decimal import Decimal
import re
from decimal import Decimal
from typing import Dict

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from sqlmodel import Session, col, select

from app.db.session import get_session
from app.models.entities import (
    BeneficiaryNeed,
    Donation,
    NeedStatus,
    NewsArticle,
    Volunteer,
    VolunteerStatus,
)
from app.templates_config import templates
from app.utils.pdf_exports import generate_beneficiaries_pdf

router = APIRouter(tags=["Admin"])


def verify_admin_session(request: Request) -> bool:
    """Helper to check active admin session cookie."""
    return request.cookies.get("admin_session") == "authenticated"


@router.get("/login", response_class=HTMLResponse)
async def get_admin_login(request: Request):
    if verify_admin_session(request):
        return RedirectResponse(url="/admin/dashboard", status_code=303)
    return templates.TemplateResponse(
        request=request,
        name="admin_login.html",
        context={"active_page": "admin"},
    )


@router.post("/login", response_class=HTMLResponse)
async def post_admin_login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
):
    if username == "admin" and password == "admin":
        response = RedirectResponse(url="/admin/dashboard", status_code=303)
        response.set_cookie(key="admin_session", value="authenticated", httponly=True)
        return response

    return templates.TemplateResponse(
        request=request,
        name="admin_login.html",
        context={
            "active_page": "admin",
            "error": "Invalid username or password credentials.",
        },
    )


@router.get("/logout")
async def admin_logout():
    response = RedirectResponse(url="/admin/login", status_code=303)
    response.delete_cookie(key="admin_session")
    return response


@router.get("/dashboard", response_class=HTMLResponse)
async def get_admin_dashboard(
    request: Request, 
    session: Session = Depends(get_session)
):
    if not verify_admin_session(request):
        return RedirectResponse(url="/admin/login", status_code=303)

    volunteers = session.exec(select(Volunteer)).all()
    donations = session.exec(
        select(Donation).order_by(col(Donation.id).desc())
    ).all()
    all_needs = session.exec(select(BeneficiaryNeed)).all()
    news_articles = session.exec(select(NewsArticle)).all()

    # Separate public assistance applications (Beneficiaries) from admin-created requests (Community Needs)
    beneficiaries = [
        need for need in all_needs 
        if need.contact_name != "Admin Internal" and need.full_address != "Admin Direct Entry"
    ]
    community_needs = [
        need for need in all_needs 
        if need.contact_name == "Admin Internal" or need.full_address == "Admin Direct Entry"
    ]

    total_volunteers = len(volunteers)
    total_donation_amount = sum((d.amount for d in donations if d.amount), Decimal("0.00"))
    total_requests = len(all_needs)
    total_news = len(news_articles)

    need_funding_progress: Dict[int, Dict[str, Decimal]] = {}
    for need in all_needs:
        if need.id is not None:
            allocated_donations = [d for d in donations if d.need_id == need.id]
            raised = sum((d.allocated_amount or Decimal("0.00") for d in allocated_donations), Decimal("0.00"))
            
            if raised == Decimal("0.00") and need.current_amount:
                raised = need.current_amount

            target = need.target_amount or Decimal("0.00")
            percent = (raised / target * Decimal("100.0")) if target > Decimal("0.00") else Decimal("0.0")

            need_funding_progress[need.id] = {
                "raised": raised,
                "target": target,
                "percentage": min(percent, Decimal("100.0")),
            }

    return templates.TemplateResponse(
        request=request,
        name="admin_dashboard.html",
        context={
            "active_page": "admin",
            "volunteers": volunteers,
            "donations": donations,
            "needs": community_needs,          # Admin-created community needs tab
            "beneficiaries": beneficiaries,    # Public assistance applications tab
            "news_articles": news_articles,
            "total_volunteers": total_volunteers,
            "total_donation_amount": f"{total_donation_amount:.2f}",
            "total_requests": total_requests,
            "total_news": total_news,
            "need_funding_progress": need_funding_progress,
        },
    )


@router.post("/needs/{need_id}/update-status")
async def update_need_status(
    need_id: int,
    request: Request,
    status: NeedStatus = Form(...),
    session: Session = Depends(get_session),
):
    if not verify_admin_session(request):
        raise HTTPException(status_code=401, detail="Unauthorized")

    need = session.get(BeneficiaryNeed, need_id)
    if not need:
        raise HTTPException(status_code=404, detail="Need record not found")

    need.status = status
    session.add(need)
    session.commit()

    return RedirectResponse(url="/admin/dashboard#beneficiaries", status_code=303)


@router.post("/volunteers/{volunteer_id}/assign-day")
def assign_volunteer_day(
    volunteer_id: int, 
    request: Request,
    assigned_day: str = Form(...), 
    session: Session = Depends(get_session)
):
    if not verify_admin_session(request):
        raise HTTPException(status_code=401, detail="Unauthorized")

    volunteer = session.get(Volunteer, volunteer_id)
    if not volunteer:
        raise HTTPException(status_code=404, detail="Volunteer not found")
        
    volunteer.assigned_day = assigned_day
    if assigned_day != "Inactive":
        volunteer.status = VolunteerStatus.ASSIGNED
    else:
        volunteer.status = VolunteerStatus.ACTIVE
        
    session.add(volunteer)
    session.commit()
    return RedirectResponse(url="/admin/dashboard#volunteers", status_code=status.HTTP_303_SEE_OTHER)

@router.get("/beneficiaries/export-pdf")
async def export_beneficiaries_pdf(
    request: Request,
    session: Session = Depends(get_session),
):
    if not verify_admin_session(request):
        raise HTTPException(status_code=401, detail="Unauthorized")

    needs = session.exec(select(BeneficiaryNeed)).all()
    pdf_buffer = generate_beneficiaries_pdf(list(needs))
    
    return StreamingResponse(
        pdf_buffer,
        media_type="application/pdf",
        headers={
            "Content-Disposition": 'attachment; filename="beneficiary_requests.pdf"'
        },
    )