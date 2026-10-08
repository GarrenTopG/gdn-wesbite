import math
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlmodel import Session, desc, select

from app.db.session import get_session
from app.models.entities import NewsArticle
from app.templatesconfig import templates

router = APIRouter(prefix="/news", tags=["News"])


@router.get("", response_class=HTMLResponse)
async def get_news_feed(
    request: Request,
    category: Optional[str] = None,
    page: int = 1,
    per_page: int = 5,
    session: Session = Depends(get_session),
):
    if per_page < 1 or per_page > 50:
        raise HTTPException(status_code=400, detail="Page size must be between 1 and 50.")

    query = select(NewsArticle)
    if category and category.strip():
        query = query.where(NewsArticle.category == category.strip())

    all_articles = session.exec(query.order_by(desc(NewsArticle.created_at))).all()
    featured_article = next((article for article in all_articles if article.is_featured), None)
    if not featured_article and all_articles and not category:
        featured_article = all_articles[0]

    feed_articles = [
        article
        for article in all_articles
        if article.id != (featured_article.id if featured_article else None)
    ]
    total_pages = max(1, math.ceil(len(feed_articles) / per_page))
    current_page = max(1, min(page, total_pages))
    start_offset = (current_page - 1) * per_page

    return templates.TemplateResponse(
        request=request,
        name="news.html",
        context={
            "active_page": "news",
            "featured_article": featured_article if current_page == 1 else None,
            "articles": feed_articles[start_offset : start_offset + per_page],
            "active_category": category,
            "current_page": current_page,
            "total_pages": total_pages,
        },
    )


@router.get("/{identifier}", response_class=HTMLResponse)
async def get_news_article_detail(
    identifier: str,
    request: Request,
    session: Session = Depends(get_session),
):
    article = None
    if identifier.isdigit():
        article = session.get(NewsArticle, int(identifier))
    if not article:
        article = session.exec(
            select(NewsArticle).where(NewsArticle.slug == identifier)
        ).first()
    if not article:
        raise HTTPException(status_code=404, detail="Article not found")

    return templates.TemplateResponse(
        request=request,
        name="newsdetail.html",
        context={
            "active_page": "news",
            "article": article,
            "current_page": 1,
            "total_pages": 1,
            "active_category": None,
        },
    )
