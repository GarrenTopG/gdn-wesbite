import re
from typing import Optional
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlmodel import Session

from app.db.session import get_session
from app.models.entities import NewsArticle
from app.routers.admin.auth import verify_admin_session

router = APIRouter()

# Admin route to create a new NewsArticle directly from the admin dashboard
@router.post("/news/add")
async def create_news_article(
    request: Request,
    title: str = Form(...),
    category: str = Form("Community"),
    summary: str = Form(...),
    content: str = Form(...),
    image_url: Optional[str] = Form(None),
    session: Session = Depends(get_session),
):
    if not verify_admin_session(request):
        raise HTTPException(status_code=401, detail="Unauthorized")

    clean_slug = re.sub(r"[^\w\s-]", "", title).strip().lower()
    slug = re.sub(r"[-\s]+", "-", clean_slug)[:50]

    article = NewsArticle(
        title=title,
        slug=slug,
        category=category,
        summary=summary,
        content=content,
        image_url=image_url if image_url and image_url.strip() else None,
    )
    session.add(article)
    session.commit()
    
    return RedirectResponse(url="/admin/dashboard?tab=news", status_code=303)

# Admin route to delete a NewsArticle from the admin dashboard
@router.post("/news/{article_id}/delete")
async def delete_news_article(
    article_id: int, 
    request: Request,
    session: Session = Depends(get_session)
):
    if not verify_admin_session(request):
        raise HTTPException(status_code=401, detail="Unauthorized")

    article = session.get(NewsArticle, article_id)
    if article:
        session.delete(article)
        session.commit()
        
    return RedirectResponse(url="/admin/dashboard?tab=news", status_code=303)

# Admin route to update a NewsArticle from the admin dashboard
@router.post("/news/{article_id}/edit")
async def update_news_article(
    article_id: int,
    request: Request,
    title: str = Form(...),
    category: str = Form(...),
    summary: str = Form(...),
    content: str = Form(...),
    image_url: Optional[str] = Form(None),
    session: Session = Depends(get_session)
):
    if not verify_admin_session(request):
        raise HTTPException(status_code=401, detail="Unauthorized")

    article = session.get(NewsArticle, article_id)
    if article:
        article.title = title
        article.category = category
        article.summary = summary
        article.content = content
        article.image_url = image_url
        session.add(article)
        session.commit()

    return RedirectResponse(url="/admin/dashboard?tab=news", status_code=303)