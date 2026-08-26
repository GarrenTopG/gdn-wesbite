from typing import Optional
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlmodel import Session, desc, select

from app.db.session import get_session
from app.models.entities import NewsArticle
from app.templates_config import templates

# Create router instance with prefix
router = APIRouter(prefix="/news", tags=["News"])


# --- SEED INITIAL DEMO NEWS DATA IF EMPTY ---
def seed_demo_news(session: Session):
    existing = session.exec(select(NewsArticle)).first()
    if not existing:
        demo_stories = [
            NewsArticle(
                title="Community Food Drive Reaches Over 500 Families Across Kuils River",
                slug="community-food-drive-reaches-over-500-families",
                category="Relief",
                summary="Through local volunteer support and generous community contributions, our winter food relief distribution successfully provided essential grocery parcels across all major wards.",
                content="Full story details regarding logistics, community hubs, volunteer coordination, and donor assistance...",
                image_url="https://images.unsplash.com/photo-1593113598332-cd288d649433?auto=format&fit=crop&w=1200&q=80",
                author="Kuils River CAN Team",
                is_featured=True,
            ),
            NewsArticle(
                title="Youth Skills Workshop Launch Announced for Next Month",
                slug="youth-skills-workshop-launch-announced",
                category="Projects",
                summary="We are excited to introduce a multi-week digital literacy and mentorship program aimed at school-leavers and job seekers.",
                content="Details on curriculum, workshop venues, registration procedures, and mentor opportunities...",
                image_url="https://images.unsplash.com/photo-1531482615713-2afd69097998?auto=format&fit=crop&w=800&q=80",
                author="Education Sub-Committee",
                is_featured=False,
            ),
            NewsArticle(
                title="Winter Blanket & Apparel Drive Kickoff",
                slug="winter-blanket-and-apparel-drive-kickoff",
                category="Community",
                summary="Drop-off points are officially open across town for clean winter clothing, warm bedding, and children's coats.",
                content="Drop-off venue addresses, accepted items list, and sorting volunteer schedules...",
                image_url="https://images.unsplash.com/photo-1488521787991-ed7bbaae773c?auto=format&fit=crop&w=800&q=80",
                author="Relief Committee",
                is_featured=False,
            ),
        ]
        for article in demo_stories:
            session.add(article)
        session.commit()


# --- NEWS FEED ROUTE ---
@router.get("", response_class=HTMLResponse)
async def get_news_feed(
    request: Request,
    category: Optional[str] = None,
    session: Session = Depends(get_session),
):
    seed_demo_news(session)

    query = select(NewsArticle)
    if category:
        query = query.where(NewsArticle.category == category)

    all_articles = session.exec(
        query.order_by(desc(NewsArticle.created_at))
    ).all()

    featured_article = next((a for a in all_articles if a.is_featured), None)
    if not featured_article and all_articles:
        featured_article = all_articles[0]

    return templates.TemplateResponse(
        request=request,
        name="news.html",
        context={
            "active_page": "news",
            "featured_article": featured_article,
            "articles": all_articles,
            "active_category": category,
        },
    )