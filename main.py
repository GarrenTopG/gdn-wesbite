from contextlib import asynccontextmanager
from fastapi import Depends, FastAPI, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select, desc
from datetime import datetime
from typing import Optional

from app.db.session import create_db_and_tables, get_session
from app.models.entities import BeneficiaryNeed, Volunteer, Donation, NewsArticle


@asynccontextmanager
async def lifespan(app: FastAPI):
    create_db_and_tables()
    yield


app = FastAPI(title="Aurorah CAN Digital Hub", lifespan=lifespan)

# Mount static files & Jinja templates
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")


@app.get("/", response_class=HTMLResponse)
def read_root(request: Request):
    return templates.TemplateResponse(
        request=request, name="index.html", context={"active_page": "home"}
    )


@app.get("/about", response_class=HTMLResponse)
def read_about(request: Request):
    return templates.TemplateResponse(
        request=request, name="about.html", context={"active_page": "about"}
    )


# --- VOLUNTEER ROUTES ---

@app.get("/volunteer", response_class=HTMLResponse)
def get_volunteer_page(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="volunteer.html",
        context={"active_page": "volunteer", "submitted": False},
    )


@app.post("/volunteer", response_class=HTMLResponse)
async def submit_volunteer_form(
    request: Request,
    session: Session = Depends(get_session),
):
    # Extract form data
    form_data = await request.form()

    # Coerce values to str to satisfy Pylance type checking
    first_name = str(form_data.get("first_name", "")).strip()
    last_name = str(form_data.get("last_name", "")).strip()
    full_name = f"{first_name} {last_name}"

    country_code = str(form_data.get("country_code", "+27"))
    phone_number = str(form_data.get("phone", "")).strip()
    formatted_phone = f"{country_code} {phone_number}"

    # Extract availability list and ensure every item is a string
    raw_days = form_data.getlist("availability")
    selected_days = [str(day) for day in raw_days if isinstance(day, str) or hasattr(day, "__str__")]
    availability_str = ", ".join(selected_days) if selected_days else "Not specified"

    # Safely extract remaining text fields
    email = str(form_data.get("email", "")).strip()
    skills = str(form_data.get("skills", "")).strip()
    location = str(form_data.get("location", "")).strip()

    # Instantiate Volunteer entity
    new_volunteer = Volunteer(
        full_name=full_name,
        phone=formatted_phone,
        email=email,
        skills=skills,
        location=location,
        availability=availability_str,
    )

    session.add(new_volunteer)
    session.commit()
    session.refresh(new_volunteer)

    return templates.TemplateResponse(
        request=request,
        name="volunteer.html",
        context={
            "active_page": "volunteer",
            "submitted": True,
            "full_name": full_name,
        },
    )

@app.get("/request-assistance", response_class=HTMLResponse)
async def get_assistance_page(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="request_assistance.html",
        context={"active_page": "assistance"},
    )


@app.post("/request-assistance", response_class=HTMLResponse)
async def submit_assistance_form(
    request: Request,
    session: Session = Depends(get_session),
):
    form_data = await request.form()

    # Extract Contact Info (Private POPIA Restricted)
    first_name = str(form_data.get("first_name", "")).strip()
    last_name = str(form_data.get("last_name", "")).strip()
    contact_name = f"{first_name} {last_name}"

    country_code = str(form_data.get("country_code", "+27"))
    phone_number = str(form_data.get("phone", "")).strip()
    contact_phone = f"{country_code} {phone_number}"

    area = str(form_data.get("location", "")).strip()
    category = str(form_data.get("need_type", "")).strip()
    urgency = str(form_data.get("urgency", "Normal")).strip()
    description = str(form_data.get("description", "")).strip()

    # Create full address (combining area and additional details if needed)
    full_address = area

    # Auto-generate a clean, public-safe anonymised title
    # e.g., "Food Parcel needed in Kuils River"
    anonymised_title = f"{category} assistance needed in {area}"
    if description:
        # Truncate description slightly for a concise summary title if provided
        short_desc = (
            description[:60] + "..." if len(description) > 60 else description
        )
        anonymised_title = f"{category}: {short_desc}"

    # Instantiate model using your exact entity fields
    new_need = BeneficiaryNeed(
        contact_name=contact_name,
        contact_phone=contact_phone,
        full_address=full_address,
        anonymised_title=anonymised_title,
        area=area,
        category=category,
        urgency=urgency,
        status="Pending",
    )

    session.add(new_need)
    session.commit()
    session.refresh(new_need)

    return templates.TemplateResponse(
        request=request,
        name="request_assistance.html",
        context={
            "active_page": "assistance",
            "submitted": True,
            "full_name": contact_name,
        },
    )

from app.models.entities import Donation  # Ensure Donation is imported


@app.get("/donate", response_class=HTMLResponse)
async def get_donate_page(request: Request):
    return templates.TemplateResponse(
        request=request, name="donate.html", context={"active_page": "donate"}
    )


@app.post("/donate", response_class=HTMLResponse)
async def submit_donation_form(
    request: Request,
    session: Session = Depends(get_session),
):
    form_data = await request.form()

    # Safe Form Extraction
    is_anon = form_data.get("is_anonymous") == "true"

    donor_name_raw = str(form_data.get("donor_name", "")).strip()
    donor_name = (
        "Anonymous Donor"
        if (is_anon or not donor_name_raw)
        else donor_name_raw
    )

    country_code = str(form_data.get("country_code", "+27"))
    phone_raw = str(form_data.get("phone", "")).strip()
    donor_phone = f"{country_code} {phone_raw}" if phone_raw else None

    # Safe Float Conversion
    raw_amount = form_data.get("amount")
    try:
        amount_val = float(str(raw_amount)) if raw_amount else 0.0
    except (ValueError, TypeError):
        amount_val = 0.0

    cause_val = str(
        form_data.get("cause", "General Fund (Where Most Needed)")
    ).strip()
    donor_email = str(form_data.get("donor_email", "")).strip()
    message_val = str(form_data.get("message", "")).strip() or None

    new_donation = Donation(
        donor_name=donor_name,
        donor_email=donor_email,
        donor_phone=donor_phone,
        amount=amount_val,
        cause=cause_val,
        payment_method="Gateway",
        message=message_val,
        is_anonymous=is_anon,
        is_verified=False,
    )

    session.add(new_donation)
    session.commit()
    session.refresh(new_donation)

    return templates.TemplateResponse(
        request=request,
        name="donate.html",
        context={
            "active_page": "donate",
            "submitted": True,
            "amount": f"{amount_val:.2f}",
        },
    )

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


# --- NEWS FEED ROUTES ---
@app.get("/news", response_class=HTMLResponse)
async def get_news_feed(
    request: Request,
    category: Optional[str] = None,
    session: Session = Depends(get_session),
):
    # Ensure initial news articles exist
    seed_demo_news(session)

    query = select(NewsArticle)
    if category:
        query = query.where(NewsArticle.category == category)

    all_articles = session.exec(query.order_by(desc(NewsArticle.created_at))).all()

    # Identify Featured Lead Story (or default to the latest story)
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