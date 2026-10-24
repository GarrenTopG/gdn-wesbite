from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlmodel import Session
from starlette.datastructures import FormData

from app.assistance_validation import parse_need_urgency
from app.db.session import get_session
from app.routers.form_data import parse_form_data
from app.routers.accounts import get_public_user
from app.models.entities import BeneficiaryNeed, NeedStatus
from app.security import (
    add_record_history,
    enforce_public_form_rate_limit,
    require_csrf,
)
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
def get_assistance_page(
    request: Request,
    session: Session = Depends(get_session),
):
    if not get_public_user(request, session):
        return RedirectResponse(
            "/account/login?next_path=%2Frequestassistance", status_code=303
        )
    return templates.TemplateResponse(
        request=request,
        name="requestassistance.html",
        context={"active_page": "assistance"},
    )


# Assistance route to handle assistance form submission
@router.post("", response_class=HTMLResponse)
def submit_assistance_form(
    request: Request,
    form_data: FormData = Depends(parse_form_data),
    session: Session = Depends(get_session),
):
    user = get_public_user(request, session)
    if not user:
        return RedirectResponse(
            "/account/login?next_path=%2Frequestassistance", status_code=303
        )
    request.state.mobile_user = user
    first_name = str(form_data.get("first_name", "")).strip()
    last_name = str(form_data.get("last_name", "")).strip()
    contact_name = f"{first_name} {last_name}".strip()

    country_code = str(form_data.get("country_code", "+27")).strip()
    phone_number = str(form_data.get("phone", "")).strip()
    contact_phone = f"{country_code} {phone_number}" if phone_number else ""

    area = str(form_data.get("location", "")).strip()
    category = str(form_data.get("need_type", "")).strip()
    request_details = str(form_data.get("description", "")).strip()
    raw_urgency = str(form_data.get("urgency", "Medium"))
    if not category:
        raise HTTPException(status_code=400, detail="Assistance category is required.")
    try:
        urgency = parse_need_urgency(raw_urgency)
    except ValueError as exc:
        raise HTTPException(
            status_code=400, detail="Invalid assistance urgency."
        ) from exc

    anonymised_title = f"{category} assistance request"

    new_need = BeneficiaryNeed(
        contact_name=contact_name,
        contact_phone=contact_phone,
        full_address=area,
        anonymised_title=anonymised_title,
        area=area,
        category=category,
        request_details=request_details,
        urgency=urgency,
        status=NeedStatus.PENDING,
    )

    session.add(new_need)
    session.flush()
    add_record_history(
        session,
        request,
        "beneficiary_need",
        new_need.id,
        "submitted",
        {"status": NeedStatus.PENDING.value},
    )
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
