import math
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlmodel import Session, desc, select

from app.db.session import get_session
from app.models.entities import NewsArticle
from app.templates_config import templates

router = APIRouter(prefix="/news", tags=["News"])


def seed_demo_news_if_empty(session: Session):
    """Utility to ensure the news table is synchronized with live stories."""
    real_stories = [
        NewsArticle(
            title="Another Big Win for Our Youth: Financial Literacy & Employment Milestones",
            slug="another-big-win-for-our-youth-financial-literacy-employment-milestones",
            category="Community Outreaches",
            summary="Our second cohort completed the Financial Literacy Program after volunteering at ECD centers, with three youth securing full-time job offers!",
            content=(
                "Today, we celebrate another milestone in the Aurorah National Youth Service Program! "
                "Our second group of youth—many of whom have been volunteering at ECD centers—has officially completed "
                "their Financial Literacy Program today. These young people have been giving their time, energy, and skills "
                "back to our communities while taking every opportunity to invest in themselves and their futures.\n\n"
                "And then came an even BIGGER reason to celebrate… THREE OF OUR YOUTH HAVE RECEIVED FULL-TIME JOB OFFERS! "
                "This is what youth development is about. It is not simply about keeping young people busy; it is about creating "
                "opportunities, building confidence, developing skills, and opening doors to sustainable employment.\n\n"
                "We are incredibly proud of these three young people and celebrate this achievement with them. May this be the "
                "beginning of many more opportunities, growth, and success! To every young person who continues to show up, volunteer, "
                "learn, participate, and push through—WE SEE YOU!\n\n"
                "From community service at ECD centers to financial literacy to employment opportunities… This is IMPACT. "
                "This is DEVELOPMENT. This is what happens when we invest in our youth! A huge thank you to everyone who continues "
                "to contribute to the growth and development of our young people and to our facilitators who are helping equip them "
                "with skills for life.\n\n"
                "Our youth have completed the introductory Financial Literacy Program, and now… WE CAN'T WAIT FOR THE ADVANCED "
                "FINANCIAL LITERACY PROGRAMME! Knowing how to earn money is important, but knowing how to manage it, grow it, "
                "plan with it, and make informed financial decisions is a whole different level! Aurorah youth are not just preparing "
                "for the future; they are already creating it."
            ),
            image_url="https://scontent.fcpt1-1.fna.fbcdn.net/v/t39.30808-6/775538639_4534272013515185_7684133947921713699_n.jpg?stp=cp6_dst-jpg_tt6&cstp=mx1600x1200&ctp=s590x590&_nc_cat=107&ccb=1-7&_nc_sid=aa7b47&_nc_ohc=DClNLT6wwMgQ7kNvwGCzUKN&_nc_oc=AdpzRgX0AiLM5O5i7s8Ndv27YsYko4lFJBRHG29Jp_Vyj9F_Ns9kjD-usvWpy1iXLGk&_nc_zt=23&_nc_ht=scontent.fcpt1-1.fna&_nc_gid=kHNoM_9deZqc0CPIxQaZaQ&_nc_ss=7b2a8&oh=00_AQK-F6DR7C4VTquSiox96m3oNRRaSndZ-ngIAWUDKJhDOg&oe=6A9DD28D",
            author="Youth Development Team",
            is_featured=True,
        ),
        NewsArticle(
            title="A Win Worth Celebrating: 3 More Youth Secure Full-Time Contracts",
            slug="a-win-worth-celebrating-3-more-youth-secure-full-time-contracts",
            category="Impact Update",
            summary="Of the 50 young people who embarked on this journey on 15 July, 8 have now secured full-time employment contracts!",
            content=(
                "We are incredibly grateful to celebrate 3 more of our youth who have secured 1-year full-time contracts!\n\n"
                "We started this journey on 15 July with 50 young people, and today, another 3 have taken a step forward into "
                "employment and new opportunities. That leaves us with 42 youth still on the journey — and we are believing "
                "that many more success stories are still to come!\n\n"
                "This is what happens when young people are given opportunities, support, skills, and a chance to believe in "
                "themselves.\n\n"
                "To our 3 youth: Congratulations! Go out there and make us proud. Your journey is only beginning!\n\n"
                "And to the remaining 42 — your opportunity is coming. Keep showing up, keep learning, keep growing, and never give up "
                "on yourself.\n\n"
                "50 started. 8 have already moved forward. 42 to go. We celebrate every single step!"
            ),
            image_url="https://scontent.fcpt1-1.fna.fbcdn.net/v/t39.30808-6/789034394_4544589515816768_4071892086812780174_n.jpg?stp=dst-jpg_tt6&cstp=mx2048x1536&ctp=s720x720&_nc_cat=101&ccb=1-7&_nc_sid=833d8c&_nc_ohc=_SWp9UafB80Q7kNvwG-DWQM&_nc_oc=Adq_GyhpOAwFhmJk8apw-0O-JT-CFaG8X2Clc8kZdPceetQDnUfnHEBEOWUaH4Az2o8&_nc_zt=23&_nc_ht=scontent.fcpt1-1.fna&_nc_gid=bkq2c_WdjZ6GsZkCVwXD_w&_nc_ss=7b2a8&oh=00_AQKdk1OD_umrlg3-pZn57hXa8cOBGdF9aYiHB5guoqU9IA&oe=6A9DC606",
            author="National Youth Service",
            is_featured=False,
        ),
        NewsArticle(
            title="Shifting Mindsets: Financial Skills Training Program with Avo Vision",
            slug="shifting-mindsets-financial-skills-training-program-with-avo-vision",
            category="Community Outreaches",
            summary="Fifteen community members gathered at Aurorah to learn, reflect, and shift mindsets regarding money, personal goals, and long-term futures.",
            content=(
                "Some mornings remind me exactly why I do the things I do. Today, we had the privilege of hosting a Financial "
                "Skills Training Programme facilitated by Babalwa from Avo Vision, where 15 community members came together to learn, "
                "reflect, ask questions, and begin thinking differently about money, goals, and the future.\n\n"
                "To many, this may have looked like 'just another workshop.' But to me… It was about hope. It was about shifting mindsets. "
                "It was about planting seeds that could change the trajectory of someone’s life.\n\n"
                "The session started with a simple question: 'What is your goal?' Not just your financial goal, but your life goal. "
                "What did you dream about when you were younger? What dreams are still alive today? And what is standing between where "
                "you are now and where you want to be?\n\n"
                "Financial literacy is not only about numbers, budgets, or saving money. It is about making informed decisions, "
                "understanding opportunities, breaking cycles, and believing that your current circumstances do not have to determine "
                "your future.\n\n"
                "Yesterday, Aurorah welcomed 50 young people into a six-month development journey. As I listened today, I couldn’t help "
                "but imagine what is possible if we walk this road together: financial literacy, business literacy, learning how to write "
                "business plans, and entrepreneurs being born.\n\n"
                "To Evervision, thank you for investing in our community and choosing to walk alongside us. Here’s to changing mindsets, "
                "creating opportunities, and building communities where dreams are not just imagined—they are achieved!"
            ),
            image_url="https://scontent.fcpt1-1.fna.fbcdn.net/v/t39.30808-6/742642431_4495666270709093_5428034783316905046_n.jpg?stp=dst-jpg_tt6&cstp=mx2048x1536&ctp=s590x590&_nc_cat=107&ccb=1-7&_nc_sid=aa7b47&_nc_ohc=Xhr_0-94828Q7kNvwEFdHSI&_nc_oc=AdrrXyBTgtAmSY9EtkbXyTdmC7aqqh6h1ifd0wywwvc4HJ63o1pjTuPX4ZzYafqc27E&_nc_zt=23&_nc_ht=scontent.fcpt1-1.fna&_nc_gid=nDb-EMZi_5GZyeQyFtf07A&_nc_ss=7b2a8&oh=00_AQIQckXYrAvCh-3X8vPvxsry3TG04e2cJnj6T2iph7yY7A&oe=6A9DEBE4",
            author="Aurorah Executive",
            is_featured=False,
        ),
        NewsArticle(
            title="Serving Hope & Warmth: Community Cook-Off Supports 400+ Residents",
            slug="serving-hope-and-warmth-community-cook-off-supports-over-400-residents",
            category="Announcements",
            summary="Aurorah volunteers and youth rallied together for a winter community cook-off, feeding over 400 residents and preparing winter relief packages.",
            content=(
                "Once again we came together for a cook-off that reminded me why we do what we do. We served around 400+ people, "
                "but in reality, it’s more than just numbers—it was the feeling that stayed with us.\n\n"
                "What really touched me was seeing the young people show up. Not because they had to, but because they wanted to—standing "
                "there, serving with so much pride and care. My Co-Creative Research for Equity and Transdisciplinary Knowledge Exchange "
                "colleague also came through, giving up their Saturday morning to be present, serve, and be part of something bigger.\n\n"
                "Winter has always been heavy for many in our communities. For the past four or five years, we’ve made it a point to show "
                "up during this season because winter hits differently. When it rains for days, when the cold cuts deep, and when there’s no "
                "electricity, there’s no way to cook or stay warm.\n\n"
                "People sometimes ask, 'Why now? It’s month-end, everyone just got paid.' But not everyone has that luxury. Some homes rely "
                "solely on social grants, and the days just before those grants come in are the hardest when cupboards are empty. That’s why "
                "we’ll keep going.\n\n"
                "Over the next few months throughout winter, we’ll continue to serve. We’re also collecting warm items: blankets, socks, "
                "beanies, and jackets. If you have something in your cupboard you haven’t worn in years, let it warm someone else.\n\n"
                "On the 12th of May, we’ll also be cooking a special meal for senior mothers to honour them and remind them that they are "
                "seen and valued. Thank you to everyone who contributed in any way, big or small, and to our youth who came out early before "
                "their soccer match just to serve!"
            ),
            image_url="https://scontent.fcpt1-1.fna.fbcdn.net/v/t39.30808-6/686952979_4425376777738043_1705183502703431523_n.jpg?stp=dst-jpg_tt6&cstp=mx1536x2048&ctp=s1536x2048&_nc_cat=108&ccb=1-7&_nc_sid=aa7b47&_nc_ohc=D097321DCdUQ7kNvwGw2hlc&_nc_oc=AdoVjzyBKCKAbL9Sg77S_qj7qOgtRSUXpz9mfQTdOxgdq5hUugkdaTj_KBKB_32e38s&_nc_zt=23&_nc_ht=scontent.fcpt1-1.fna&_nc_gid=lsiTa24n8yMTjUCvYHPirg&_nc_ss=7b2a8&oh=00_AQJhUtFmpULcdUKNDnqhcAnguvKe7V1Uu6UMARgn2Ftd_Q&oe=6A9DD80B",
            author="Relief Committee",
            is_featured=False,
        ),
    ]

    existing_slugs = {a.slug for a in session.exec(select(NewsArticle)).all()}
    target_slugs = {a.slug for a in real_stories}

    # If the database contains old articles that don't match our real stories, clear them
    if not target_slugs.issubset(existing_slugs):
        for old in session.exec(select(NewsArticle)).all():
            session.delete(old)
        session.commit()

        for article in real_stories:
            session.add(article)
        session.commit()


@router.get("", response_class=HTMLResponse)
async def get_news_feed(
    request: Request,
    category: Optional[str] = None,
    page: int = 1,
    per_page: int = 5,
    session: Session = Depends(get_session),
):
    seed_demo_news_if_empty(session)

    query = select(NewsArticle)
    if category and category.strip():
        query = query.where(NewsArticle.category == category.strip())

    all_articles = session.exec(query.order_by(desc(NewsArticle.created_at))).all()

    featured_article = next((a for a in all_articles if a.is_featured), None)
    if not featured_article and all_articles and not category:
        featured_article = all_articles[0]

    feed_articles = [
        a for a in all_articles if a.id != (featured_article.id if featured_article else None)
    ]

    total_feed_items = len(feed_articles)
    total_pages = max(1, math.ceil(total_feed_items / per_page))
    current_page = max(1, min(page, total_pages))

    start_offset = (current_page - 1) * per_page
    paginated_feed = feed_articles[start_offset : start_offset + per_page]

    return templates.TemplateResponse(
        request=request,
        name="news.html",
        context={
            "active_page": "news",
            "featured_article": featured_article if current_page == 1 else None,
            "articles": paginated_feed,
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
    """Retrieves an article by integer ID or text slug."""
    article = None
    if identifier.isdigit():
        article = session.get(NewsArticle, int(identifier))

    if not article:
        article = session.exec(select(NewsArticle).where(NewsArticle.slug == identifier)).first()

    if not article:
        raise HTTPException(status_code=404, detail="Article not found")

    return templates.TemplateResponse(
        request=request,
        name="news_detail.html",
        context={
            "active_page": "news",
            "article": article,
            "current_page": 1,
            "total_pages": 1,
            "active_category": None,
        },
    )