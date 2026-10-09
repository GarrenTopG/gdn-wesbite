from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlmodel import Session

from app.db.session import get_session
from app.models.entities import Volunteer, VolunteerStatus
from app.security import add_record_history, enforce_public_form_rate_limit, require_csrf
from app.templatesconfig import templates

router = APIRouter(
    prefix="/volunteer",
    tags=["Volunteers"],
    dependencies=[
        Depends(require_csrf),
        Depends(enforce_public_form_rate_limit),
    ],
)

# Volunteer route to render the volunteer page
@router.get("", response_class=HTMLResponse)
async def get_volunteer_page(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="volunteer.html",
        context={"active_page": "volunteer", "submitted": False},
    )

# Volunteer route to handle volunteer form submission
@router.post("", response_class=HTMLResponse)
async def submit_volunteer_form(
    request: Request,
    session: Session = Depends(get_session),
):
    form_data = await request.form()

    # Name Parsing
    first_name = str(form_data.get("first_name", "")).strip()
    last_name = str(form_data.get("last_name", "")).strip()
    full_name = f"{first_name} {last_name}".strip()

    # Contact Details
    country_code = str(form_data.get("country_code", "+27")).strip()
    phone_number = str(form_data.get("phone", "")).strip()
    formatted_phone = f"{country_code} {phone_number}" if phone_number else ""
    email = str(form_data.get("email", "")).strip()

    # Multi-Key Form Array handling for available_days
    raw_days = (
        form_data.getlist("availability")
        or form_data.getlist("availability[]")
        or form_data.getlist("days")
    )
    selected_days = [str(day).strip() for day in raw_days if str(day).strip()]
    availability_str = ", ".join(selected_days) if selected_days else "Flexible / Not Specified"

    skills = str(form_data.get("skills", "")).strip()
    location = str(form_data.get("location", "")).strip()

    # Save selected_days directly into available_days list field
    new_volunteer = Volunteer(
        full_name=full_name,
        phone=formatted_phone,
        email=email,
        skills=skills,
        location=location,
        availability=availability_str,
        available_days=selected_days,  # <--- CRITICAL FIX: Populates volunteer.available_days list
        status=VolunteerStatus.ACTIVE,
    )

    session.add(new_volunteer)
    session.flush()
    add_record_history(
        session,
        request,
        "volunteer",
        new_volunteer.id,
        "submitted",
        {"onboarding_status": new_volunteer.onboarding_status},
    )
    session.commit()
    session.refresh(new_volunteer)

    # Partial rendering support for HTMX
    if request.headers.get("HX-Request"):
        return templates.TemplateResponse(
            request=request,
            name="partials/_volunteer_success.html",
            context={"full_name": full_name},
        )

    return templates.TemplateResponse(
        request=request,
        name="volunteer.html",
        context={
            "active_page": "volunteer",
            "submitted": True,
            "full_name": full_name,
        },
    )