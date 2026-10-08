from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlmodel import Session

from app.db.session import get_session
from app.models.entities import BeneficiaryNeed, NeedUrgency, NeedStatus
from app.security import enforce_public_form_rate_limit, require_csrf
from app.templatesconfig import templates

router = APIRouter(
    prefix="/requestassistance",
    tags=["Assistance"],
    dependencies=[
        Depends(require_csrf),
        Depends(enforce_public_form_rate_limit),
    ],
)

# Assistance route to render the assistance request page
@router.get("", response_class=HTMLResponse)
async def get_assistance_page(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="requestassistance.html",
        context={"active_page": "assistance"},
    )

# Assistance route to handle assistance form submission
@router.post("", response_class=HTMLResponse)
async def submit_assistance_form(
    request: Request,
    session: Session = Depends(get_session),
):
    form_data = await request.form()

    # Personal Data Parsing
    first_name = str(form_data.get("first_name", "")).strip()
    last_name = str(form_data.get("last_name", "")).strip()
    contact_name = f"{first_name} {last_name}".strip()

    country_code = str(form_data.get("country_code", "+27")).strip()
    phone_number = str(form_data.get("phone", "")).strip()
    contact_phone = f"{country_code} {phone_number}" if phone_number else ""

    area = str(form_data.get("location", "")).strip()
    category = str(form_data.get("need_type", "")).strip()
    request_details = str(form_data.get("description", "")).strip()
    raw_urgency = str(form_data.get("urgency", "Medium")).strip().capitalize()

    # Map raw string to Enum safely
    try:
        urgency_enum = NeedUrgency(raw_urgency)
    except ValueError:
        urgency_enum = NeedUrgency.MEDIUM

    anonymised_title = f"{category} assistance request"

    new_need = BeneficiaryNeed(
        contact_name=contact_name,
        contact_phone=contact_phone,
        full_address=area,
        anonymised_title=anonymised_title,
        area=area,
        category=category,
        request_details=request_details,
        urgency=urgency_enum,
        status=NeedStatus.PENDING,
    )

    session.add(new_need)
    session.commit()
    session.refresh(new_need)

    if request.headers.get("HX-Request"):
        return templates.TemplateResponse(
            request=request,
            name="partials/_assistance_success.html",
            context={"full_name": contact_name, "need_id": new_need.id},
        )

    return templates.TemplateResponse(
        request=request,
        name="requestassistance.html",
        context={
            "active_page": "assistance",
            "submitted": True,
            "full_name": contact_name,
        },
    )