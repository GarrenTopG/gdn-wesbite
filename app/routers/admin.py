from typing import Dict
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlmodel import Session, select

from app.db.session import get_session
from app.models.entities import (
    BeneficiaryNeed,
    Donation,
    NewsArticle,
    Volunteer,
    VolunteerMatch,
)
from app.templates_config import templates

# Create router instance with prefix
router = APIRouter(prefix="/admin", tags=["Admin"])


# --- AUTH & DASHBOARD ROUTES ---

@router.get("/login", response_class=HTMLResponse)
async def get_admin_login(request: Request):
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
        response.set_cookie(key="admin_session", value="authenticated")
        return response

    return templates.TemplateResponse(
        request=request,
        name="admin_login.html",
        context={
            "active_page": "admin",
            "error": "Invalid username or password credentials.",
        },
    )


@router.get("/dashboard", response_class=HTMLResponse)
async def get_admin_dashboard(
    request: Request, session: Session = Depends(get_session)
):
    volunteers = session.exec(select(Volunteer)).all()
    donations = session.exec(
        select(Donation).order_by(Donation.id.desc())
    ).all()
    needs = session.exec(select(BeneficiaryNeed)).all()
    news_articles = session.exec(select(NewsArticle)).all()

    total_volunteers = len(volunteers)
    total_donation_amount = (
        sum(d.amount for d in donations if d.amount) if donations else 0.0
    )
    total_requests = len(needs)
    total_news = len(news_articles)

    # Calculate dynamically raised totals per targeted need
    need_funding_progress: Dict[int, Dict[str, float]] = {}
    for need in needs:
        if need.id is not None:
            # Sum all verified donations allocated to this need
            allocated_donations = [
                d for d in donations if d.need_id == need.id and d.is_verified
            ]
            raised = sum(d.amount for d in allocated_donations if d.amount)
            target = need.target_amount or 0.0
            percent = (raised / target * 100.0) if target > 0 else 0.0

            need_funding_progress[need.id] = {
                "raised": raised,
                "target": target,
                "percentage": min(percent, 100.0),
            }

    return templates.TemplateResponse(
        request=request,
        name="admin_dashboard.html",
        context={
            "active_page": "admin",
            "volunteers": volunteers,
            "donations": donations,
            "needs": needs,
            "news_articles": news_articles,
            "total_volunteers": total_volunteers,
            "total_donation_amount": total_donation_amount,
            "total_requests": total_requests,
            "total_news": total_news,
            "need_funding_progress": need_funding_progress,
        },
    )


# --- PHASE 3: DONATION MANAGEMENT ENDPOINTS ---

@router.post("/donations/{donation_id}/verify")
async def verify_donation(
    donation_id: int,
    session: Session = Depends(get_session),
):
    donation = session.get(Donation, donation_id)
    if not donation:
        raise HTTPException(status_code=404, detail="Donation record not found")

    donation.is_verified = True
    session.add(donation)
    session.commit()

    return JSONResponse(
        content={
            "status": "success",
            "message": f"Donation #{donation_id} verified successfully.",
        }
    )


# --- BENEFICIARY NEED ACTION ENDPOINTS ---

@router.post("/needs/add")
async def create_community_need(
    anonymised_title: str = Form(...),
    area: str = Form(...),
    category: str = Form(...),
    urgency: str = Form("Medium"),
    contact_name: str = Form("Admin Internal"),
    contact_phone: str = Form("+27 00 000 0000"),
    full_address: str = Form("Admin Direct Entry"),
    target_amount: float = Form(0.0),
    session: Session = Depends(get_session),
):
    new_need = BeneficiaryNeed(
        contact_name=contact_name,
        contact_phone=contact_phone,
        full_address=full_address,
        anonymised_title=anonymised_title,
        area=area,
        category=category,
        urgency=urgency,
        target_amount=target_amount,
        status="Pending",
    )
    session.add(new_need)
    session.commit()
    return RedirectResponse(url="/admin/dashboard", status_code=303)


@router.post("/needs/{need_id}/status")
async def update_need_status(
    need_id: int,
    status: str = Form(...),
    session: Session = Depends(get_session),
):
    need = session.get(BeneficiaryNeed, need_id)
    if not need:
        raise HTTPException(status_code=404, detail="Need record not found")

    need.status = status
    session.add(need)
    session.commit()
    return JSONResponse(
        content={
            "status": "success",
            "message": f"Need #{need_id} status updated to {status}",
        }
    )


# --- NEWS ENDPOINTS ---

@router.post("/news/add")
async def create_news_article(
    title: str = Form(...),
    category: str = Form("Community"),
    summary: str = Form(...),
    content: str = Form(...),
    image_url: str = Form(None),
    session: Session = Depends(get_session),
):
    slug = title.lower().replace(" ", "-")[:50]
    article = NewsArticle(
        title=title,
        slug=slug,
        category=category,
        summary=summary,
        content=content,
        image_url=image_url,
    )
    session.add(article)
    session.commit()
    return RedirectResponse(url="/admin/dashboard", status_code=303)


@router.post("/news/{article_id}/delete")
async def delete_news_article(
    article_id: int, session: Session = Depends(get_session)
):
    article = session.get(NewsArticle, article_id)
    if article:
        session.delete(article)
        session.commit()
    return RedirectResponse(url="/admin/dashboard", status_code=303)


# --- VOLUNTEER MATCHING ENDPOINTS ---

@router.post("/needs/{need_id}/assign-volunteer")
async def assign_volunteer_to_need(
    need_id: int,
    volunteer_id: int = Form(...),
    session: Session = Depends(get_session),
):
    need = session.get(BeneficiaryNeed, need_id)
    volunteer = session.get(Volunteer, volunteer_id)

    if not need or not volunteer:
        raise HTTPException(
            status_code=404, detail="Need or Volunteer record missing"
        )

    assert need.id is not None
    assert volunteer.id is not None

    match = VolunteerMatch(
        need_id=need.id,
        volunteer_id=volunteer.id,
        matched_by_admin="Admin Direct Match",
    )
    need.status = "In Progress"
    volunteer.status = "Assigned"

    session.add(match)
    session.add(need)
    session.add(volunteer)
    session.commit()

    return JSONResponse(
        content={
            "status": "success",
            "message": f"Assigned {volunteer.full_name} to '{need.anonymised_title}'",
        }
    )