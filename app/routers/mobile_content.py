from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import true
from sqlmodel import Session, select

from app.db.session import get_session
from app.models.entities import (
    BeneficiaryNeed,
    NeedStatus,
    NewsArticle,
    NewsStatus,
    User,
    VolunteerOffer,
)
from app.routers.donations import (
    _community_need_excerpt,
    _public_community_needs_statement,
)
from app.routers.mobile_dependencies import _rate_limit, require_mobile_user
from app.schemas.mobile import (
    NeedResponse,
    NewsItemResponse,
    OfferAssistanceRequest,
    SuccessResponse,
)
from app.security import add_record_history

router = APIRouter()


@router.get("/news", response_model=list[NewsItemResponse])
def get_news(session: Session = Depends(get_session)):
    articles = session.exec(
        select(NewsArticle)
        .where(
            NewsArticle.status == NewsStatus.PUBLISHED.value,
            NewsArticle.archived_at.is_(None),
        )
        .order_by(NewsArticle.created_at.desc())
    ).all()
    return [
        {
            "id": article.id,
            "title": article.title,
            "summary": article.summary,
            "content": article.content,
            "image_url": article.image_url,
            "timestamp": article.created_at.isoformat(),
            "category": article.category,
        }
        for article in articles
    ]


@router.get("/needs", response_model=list[NeedResponse])
def get_needs(session: Session = Depends(get_session)):
    rows = session.exec(_public_community_needs_statement()).all()
    results = []
    for row in rows:
        urgency_val = (
            row.urgency.value if hasattr(row.urgency, "value") else str(row.urgency)
        )
        status_val = (
            row.status.value if hasattr(row.status, "value") else str(row.status)
        )
        excerpt = _community_need_excerpt(row.article)
        created_at_val = getattr(row, "created_at", None)
        created_at_str = created_at_val.isoformat() if created_at_val else None
        deadline_str = row.deadline.isoformat() if row.deadline else None

        results.append(
            {
                "needId": row.id,
                "title": row.anonymised_title,
                "description": excerpt or getattr(row, "request_details", "") or "",
                "location": row.area,
                "priority": urgency_val,
                "category": row.category,
                "status": status_val,
                "createdAt": created_at_str,
                "targetAmount": row.target_amount,
                "currentAmount": row.current_amount,
                "imageUrl": row.image_url,
                "imageAlt": row.image_alt,
                "article": row.article,
                "articleExcerpt": excerpt,
                "deadline": deadline_str,
            }
        )
    return results


@router.post(
    "/needs/offer-assistance",
    dependencies=[Depends(_rate_limit("mobile-offer-assistance", 5, 3600))],
    response_model=SuccessResponse,
)
def offer_assistance(
    body: OfferAssistanceRequest,
    request: Request,
    user: User = Depends(require_mobile_user),
    session: Session = Depends(get_session),
):
    if body.user_email.strip().lower() != user.email:
        raise HTTPException(
            status_code=403, detail="You can only offer help using your own account."
        )
    volunteer_skill = body.volunteer_skill.strip()
    if not volunteer_skill:
        raise HTTPException(
            status_code=400, detail="Please describe a volunteer skill."
        )
    need = session.get(BeneficiaryNeed, body.need_id)
    if (
        not need
        or not need.is_community_need
        or need.archived_at is not None
        or need.status in {NeedStatus.FULFILLED, NeedStatus.REJECTED}
    ):
        raise HTTPException(status_code=404, detail="Community need not found.")
    offer = VolunteerOffer(
        need_id=need.id,
        user_id=user.id,
        volunteer_skill=volunteer_skill,
        notes=body.notes.strip(),
    )
    session.add(offer)
    session.flush()
    add_record_history(
        session,
        request,
        "volunteer_offer",
        offer.id,
        "submitted",
        {"need_id": need.id},
    )
    session.commit()
    return {"success": True, "message": "Your offer to help has been submitted."}
