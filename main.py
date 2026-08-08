from contextlib import asynccontextmanager
from fastapi import Depends, FastAPI, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlmodel import Session
from datetime import datetime
from typing import Optional

from app.db.session import create_db_and_tables, get_session
from app.models.entities import BeneficiaryNeed, Volunteer


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