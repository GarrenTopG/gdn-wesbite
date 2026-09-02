from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlmodel import Session

from app.db.session import get_session
from app.models.entities import Volunteer, VolunteerStatus
from app.templates_config import templates

router = APIRouter(prefix="/volunteer", tags=["Volunteers"])


@router.get("", response_class=HTMLResponse)
async def get_volunteer_page(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="volunteer.html",
        context={"active_page": "volunteer", "submitted": False},
    )


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

    # Form Multiselect / Array handling for availability
    raw_days = form_data.getlist("availability")
    selected_days = [str(day).strip() for day in raw_days if str(day).strip()]
    availability_str = ", ".join(selected_days) if selected_days else "Not specified"

    skills = str(form_data.get("skills", "")).strip()
    location = str(form_data.get("location", "")).strip()

    new_volunteer = Volunteer(
        full_name=full_name,
        phone=formatted_phone,
        email=email,
        skills=skills,
        location=location,
        availability=availability_str,
        status=VolunteerStatus.ACTIVE,
    )

    session.add(new_volunteer)
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