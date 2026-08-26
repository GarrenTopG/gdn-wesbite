from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlmodel import Session

from app.db.session import get_session
from app.models.entities import BeneficiaryNeed
from app.templates_config import templates

# Create router instance with prefix
router = APIRouter(prefix="/request-assistance", tags=["Assistance"])


@router.get("", response_class=HTMLResponse)
async def get_assistance_page(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="request_assistance.html",
        context={"active_page": "assistance"},
    )


@router.post("", response_class=HTMLResponse)
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

    full_address = area

    # Auto-generate anonymised title
    anonymised_title = f"{category} assistance needed in {area}"
    if description:
        short_desc = (
            description[:60] + "..." if len(description) > 60 else description
        )
        anonymised_title = f"{category}: {short_desc}"

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