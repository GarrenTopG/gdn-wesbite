import re
from typing import Optional
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlmodel import Session, select

from app.db.session import get_session
from app.models.entities import NewsArticle, NewsStatus
from app.routers.admin.auth import verify_staff_session
from app.security import add_audit_event, add_record_history, now_utc, permission_required
from app.templatesconfig import templates

router = APIRouter(dependencies=[Depends(permission_required("news.write"))])

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
    if not verify_staff_session(request):
        raise HTTPException(status_code=401, detail="Unauthorized")

    clean_slug = re.sub(r"[^\w\s-]", "", title).strip().lower()
    base_slug = re.sub(r"[-\s]+", "-", clean_slug)[:50] or "article"
    slug = base_slug
    suffix = 2
    while session.exec(select(NewsArticle).where(NewsArticle.slug == slug)).first():
        suffix_text = f"-{suffix}"
        slug = f"{base_slug[:50 - len(suffix_text)]}{suffix_text}"
        suffix += 1

    article = NewsArticle(
        title=title,
        slug=slug,
        category=category,
        summary=summary,
        content=content,
        image_url=image_url if image_url and image_url.strip() else None,
        status=NewsStatus.DRAFT.value,
    )
    session.add(article)
    session.flush()
    add_record_history(
        session, request, "news_article", article.id, "article_created"
    )
    add_audit_event(session, request, "news.created", "news_article", article.id)
    session.commit()
    
    return RedirectResponse(url="/admin/dashboard?tab=news", status_code=303)

# Admin route to delete a NewsArticle from the admin dashboard
@router.post("/news/{article_id}/delete")
async def delete_news_article(
    article_id: int, 
    request: Request,
    session: Session = Depends(get_session)
):
    if not verify_staff_session(request):
        raise HTTPException(status_code=401, detail="Unauthorized")

    article = session.get(NewsArticle, article_id)
    if not article or article.archived_at is not None:
        return RedirectResponse(url="/admin/dashboard?tab=news", status_code=303)
    article.status = NewsStatus.ARCHIVED.value
    article.archived_at = now_utc()
    session.add(article)
    add_record_history(session, request, "news_article", article_id, "archived")
    add_audit_event(session, request, "news.archived", "news_article", article_id)
    session.commit()
        
    return RedirectResponse(url="/admin/dashboard?tab=news", status_code=303)


@router.post("/news/{article_id}/status")
async def update_news_status(
    article_id: int,
    request: Request,
    status: str = Form(...),
    session: Session = Depends(get_session),
):
    article = session.get(NewsArticle, article_id)
    if not article or article.archived_at is not None:
        raise HTTPException(status_code=404, detail="News article not found.")
    transitions = {
        NewsStatus.DRAFT.value: {NewsStatus.PREVIEW.value, NewsStatus.ARCHIVED.value},
        NewsStatus.PREVIEW.value: {
            NewsStatus.DRAFT.value,
            NewsStatus.PUBLISHED.value,
            NewsStatus.ARCHIVED.value,
        },
        NewsStatus.PUBLISHED.value: {NewsStatus.ARCHIVED.value},
        NewsStatus.ARCHIVED.value: set(),
    }
    if status not in transitions.get(article.status, set()):
        raise HTTPException(
            status_code=409,
            detail=f"Invalid news lifecycle transition from {article.status}.",
        )
    previous = article.status
    article.status = status
    if status == NewsStatus.ARCHIVED.value:
        article.archived_at = now_utc()
    session.add(article)
    add_record_history(
        session,
        request,
        "news_article",
        article_id,
        "lifecycle_changed",
        {"from": previous, "to": status},
    )
    add_audit_event(
        session,
        request,
        "news.lifecycle_changed",
        "news_article",
        article_id,
        {"from": previous, "to": status},
    )
    session.commit()
    return RedirectResponse(url="/admin/dashboard?tab=news", status_code=303)


@router.get("/news/{article_id}/preview")
async def preview_news_article(
    article_id: int,
    request: Request,
    session: Session = Depends(get_session),
):
    article = session.get(NewsArticle, article_id)
    if not article or article.status == NewsStatus.ARCHIVED.value:
        raise HTTPException(status_code=404, detail="News article not found.")
    add_audit_event(session, request, "news.previewed", "news_article", article_id)
    session.commit()
    return templates.TemplateResponse(
        request=request,
        name="adminnews_preview.html",
        context={
            "active_page": "admin",
            "staff_user": request.state.staff_user,
            "article": article,
        },
    )

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
    if not verify_staff_session(request):
        raise HTTPException(status_code=401, detail="Unauthorized")

    article = session.get(NewsArticle, article_id)
    if article and article.archived_at is None:
        article.title = title
        article.category = category
        article.summary = summary
        article.content = content
        article.image_url = image_url
        session.add(article)
        add_record_history(session, request, "news_article", article_id, "content_updated")
        add_audit_event(session, request, "news.updated", "news_article", article_id)
        session.commit()

    return RedirectResponse(url="/admin/dashboard?tab=news", status_code=303)