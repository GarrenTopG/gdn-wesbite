import re
from decimal import Decimal
from typing import Dict
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlmodel import Session, col, select

from app.db.session import get_session
from app.models.entities import BeneficiaryNeed, Donation, NewsArticle, Volunteer
from app.templates_config import templates

router = APIRouter()


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
    needs = session.exec(select(BeneficiaryNeed)).all()
    news_articles = session.exec(select(NewsArticle)).all()

    total_volunteers = len(volunteers)
    total_donation_amount = sum((d.amount for d in donations if d.amount), Decimal("0.00"))
    total_requests = len(needs)
    total_news = len(news_articles)

    need_funding_progress: Dict[int, Dict[str, Decimal]] = {}
    for need in needs:
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
            "needs": needs,
            "news_articles": news_articles,
            "total_volunteers": total_volunteers,
            "total_donation_amount": f"{total_donation_amount:.2f}",
            "total_requests": total_requests,
            "total_news": total_news,
            "need_funding_progress": need_funding_progress,
        },
    )