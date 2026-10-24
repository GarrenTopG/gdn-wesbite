from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from urllib.parse import urlsplit
from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from sqlmodel import Session

from app.db.session import get_session
from app.models.entities import (
    BeneficiaryNeed,
    NeedStatus,
    NeedUrgency,
    Volunteer,
    VolunteerMatch,
    VolunteerOffer,
    VolunteerStatus,
    set_need_status,
)
from app.routers.admin.auth import verify_staff_session
from app.security import (
    add_audit_event,
    add_record_history,
    now_utc,
    permission_required,
)

router = APIRouter(dependencies=[Depends(permission_required("needs.write"))])


def _has_cent_precision(amount: Decimal) -> bool:
    try:
        return amount.quantize(Decimal("0.01")) == amount
    except InvalidOperation:
        return False


def _community_content_fields(
    *, article: str, image_url: str, image_alt: str
) -> dict[str, str | None]:
    article = article.strip()
    image_url = image_url.strip()
    image_alt = image_alt.strip()
    if len(article) > 20000:
        raise HTTPException(status_code=400, detail="The article is too long.")
    if len(image_url) > 2048 or len(image_alt) > 500:
        raise HTTPException(status_code=400, detail="Image details are too long.")
    if image_url:
        try:
            parsed_url = urlsplit(image_url)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid image URL.") from exc
        if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
            raise HTTPException(
                status_code=400,
                detail="Image URLs must use an HTTP or HTTPS URL.",
            )
        if not image_alt:
            raise HTTPException(
                status_code=400,
                detail="Provide descriptive alt text for the image.",
            )
    return {
        "article": article or None,
        "image_url": image_url or None,
        "image_alt": image_alt or None,
    }


def _validate_community_need_labels(
    anonymised_title: str, area: str, category: str
) -> tuple[str, str, str]:
    anonymised_title = anonymised_title.strip()
    area = area.strip()
    category = category.strip()
    if (
        not anonymised_title
        or len(anonymised_title) > 255
        or not area
        or len(area) > 255
        or not category
        or len(category) > 100
    ):
        raise HTTPException(
            status_code=400,
            detail="Enter a valid title, area, and category.",
        )
    return anonymised_title, area, category


# Admin route to create a new BeneficiaryNeed directly from the admin dashboard
@router.post("/needs/add")
def create_community_need(
    request: Request,
    anonymised_title: str = Form(...),
    area: str = Form(...),
    category: str = Form(...),
    urgency: str = Form("Medium"),
    contact_name: str = Form(""),
    contact_phone: str = Form(""),
    full_address: str = Form(""),
    target_amount: str = Form("0.00"),
    deadline: str = Form(""),
    article: str = Form(""),
    image_url: str = Form(""),
    image_alt: str = Form(""),
    session: Session = Depends(get_session),
):
    if not verify_staff_session(request):
        raise HTTPException(status_code=401, detail="Unauthorized")

    anonymised_title, area, category = _validate_community_need_labels(
        anonymised_title, area, category
    )
    try:
        parsed_target = Decimal(target_amount)
    except (InvalidOperation, ValueError):
        raise HTTPException(status_code=400, detail="Invalid target amount.")
    if not parsed_target.is_finite() or parsed_target < Decimal("0.00"):
        raise HTTPException(
            status_code=400, detail="Target amount must be zero or greater."
        )
    if not _has_cent_precision(parsed_target):
        raise HTTPException(
            status_code=400, detail="Target amount may have at most two decimals."
        )
    try:
        parsed_deadline = datetime.fromisoformat(deadline) if deadline.strip() else None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid need deadline.") from exc
    if parsed_deadline and parsed_deadline.tzinfo is None:
        parsed_deadline = parsed_deadline.replace(tzinfo=timezone.utc)

    try:
        urgency_enum = NeedUrgency(urgency)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid urgency value.")

    content_fields = _community_content_fields(
        article=article, image_url=image_url, image_alt=image_alt
    )
    new_need = BeneficiaryNeed(
        contact_name=contact_name,
        contact_phone=contact_phone,
        full_address=full_address,
        anonymised_title=anonymised_title,
        area=area,
        category=category,
        urgency=urgency_enum,
        target_amount=parsed_target,
        deadline=parsed_deadline,
        **content_fields,
        status=NeedStatus.PENDING,
        is_community_need=True,
    )
    session.add(new_need)
    session.flush()
    add_record_history(
        session,
        request,
        "beneficiary_need",
        new_need.id,
        "need_created",
        {"deadline": parsed_deadline.isoformat() if parsed_deadline else None},
    )
    add_audit_event(session, request, "need.created", "beneficiary_need", new_need.id)
    session.commit()

    return RedirectResponse(url="/admin/dashboard?tab=needs", status_code=303)


@router.post("/needs/{need_id}/edit")
def edit_community_need(
    need_id: int,
    request: Request,
    anonymised_title: str = Form(...),
    area: str = Form(...),
    category: str = Form(...),
    urgency: str = Form(...),
    target_amount: str = Form(...),
    deadline: str = Form(""),
    article: str = Form(""),
    image_url: str = Form(""),
    image_alt: str = Form(""),
    session: Session = Depends(get_session),
):
    if not verify_staff_session(request):
        raise HTTPException(status_code=401, detail="Unauthorized")

    need = session.get(BeneficiaryNeed, need_id)
    if not need or not need.is_community_need or need.archived_at is not None:
        raise HTTPException(status_code=404, detail="Community need not found.")

    anonymised_title, area, category = _validate_community_need_labels(
        anonymised_title, area, category
    )
    try:
        parsed_target = Decimal(target_amount)
    except (InvalidOperation, ValueError) as exc:
        raise HTTPException(status_code=400, detail="Invalid target amount.") from exc
    if not parsed_target.is_finite() or parsed_target < Decimal("0.00"):
        raise HTTPException(
            status_code=400, detail="Target amount must be zero or greater."
        )
    if not _has_cent_precision(parsed_target):
        raise HTTPException(
            status_code=400, detail="Target amount may have at most two decimals."
        )
    try:
        parsed_deadline = datetime.fromisoformat(deadline) if deadline.strip() else None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid need deadline.") from exc
    if parsed_deadline and parsed_deadline.tzinfo is None:
        parsed_deadline = parsed_deadline.replace(tzinfo=timezone.utc)
    try:
        urgency_enum = NeedUrgency(urgency)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid urgency value.") from exc

    content_fields = _community_content_fields(
        article=article, image_url=image_url, image_alt=image_alt
    )
    updates = {
        "anonymised_title": anonymised_title,
        "area": area,
        "category": category,
        "urgency": urgency_enum,
        "target_amount": parsed_target,
        "deadline": parsed_deadline,
        **content_fields,
    }
    changed_fields = [
        name for name, value in updates.items() if getattr(need, name) != value
    ]
    for name, value in updates.items():
        setattr(need, name, value)
    if changed_fields:
        session.add(need)
        add_record_history(
            session,
            request,
            "beneficiary_need",
            need_id,
            "need_updated",
            {"fields": changed_fields},
        )
        add_audit_event(
            session,
            request,
            "need.updated",
            "beneficiary_need",
            need_id,
            {"fields": changed_fields},
        )
        session.commit()

    return RedirectResponse(url="/admin/dashboard?tab=needs", status_code=303)


@router.post("/needs/offers/{offer_id}/review")
def review_volunteer_offer(
    offer_id: int,
    request: Request,
    session: Session = Depends(get_session),
):
    if not verify_staff_session(request):
        raise HTTPException(status_code=401, detail="Unauthorized")

    offer = session.get(VolunteerOffer, offer_id)
    if not offer:
        raise HTTPException(status_code=404, detail="Volunteer offer not found.")
    if offer.status != "Pending":
        raise HTTPException(
            status_code=409, detail="Volunteer offer has already been reviewed."
        )

    offer.status = "Reviewed"
    session.add(offer)
    add_record_history(
        session,
        request,
        "volunteer_offer",
        offer.id,
        "reviewed",
        {"status": offer.status},
    )
    add_audit_event(
        session,
        request,
        "volunteer_offer.reviewed",
        "volunteer_offer",
        offer.id,
    )
    session.commit()
    return RedirectResponse(url="/admin/dashboard?tab=needs", status_code=303)


# Admin route to delete a BeneficiaryNeed from the admin dashboard
@router.post("/needs/delete/{need_id}")
def delete_community_need(
    need_id: int, request: Request, session: Session = Depends(get_session)
):
    if not verify_staff_session(request):
        raise HTTPException(status_code=401, detail="Unauthorized")

    need = session.get(BeneficiaryNeed, need_id)
    if not need or not need.is_community_need or need.archived_at is not None:
        raise HTTPException(status_code=404, detail="Community need not found")
    need.archived_at = now_utc()
    session.add(need)
    add_record_history(session, request, "beneficiary_need", need_id, "archived")
    add_audit_event(session, request, "need.archived", "beneficiary_need", need_id)
    session.commit()

    return RedirectResponse(url="/admin/dashboard?tab=needs", status_code=303)


# Admin route to update the status of a BeneficiaryNeed from the admin dashboard
@router.post("/needs/{need_id}/status")
def update_need_status(
    need_id: int,
    request: Request,
    status: str = Form(...),
    reason: str = Form(""),
    session: Session = Depends(get_session),
):
    if not verify_staff_session(request):
        raise HTTPException(status_code=401, detail="Unauthorized")

    need = session.get(BeneficiaryNeed, need_id)
    if not need or need.archived_at is not None:
        raise HTTPException(status_code=404, detail="Need record not found")

    try:
        new_status = NeedStatus(status)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid need status.")
    reason = reason.strip()
    if new_status in {NeedStatus.FULFILLED, NeedStatus.REJECTED} and not reason:
        raise HTTPException(
            status_code=400,
            detail="A reason is required when closing or rejecting a need.",
        )
    old_status = getattr(need.status, "value", need.status)
    set_need_status(need, new_status)

    session.add(need)
    add_record_history(
        session,
        request,
        "beneficiary_need",
        need_id,
        "status_changed",
        {"from": old_status, "to": new_status.value, "reason": reason or None},
    )
    add_audit_event(
        session,
        request,
        "need.status_changed",
        "beneficiary_need",
        need_id,
        {"status": new_status.value},
    )
    session.commit()

    if request.headers.get("HX-Request"):
        return Response(status_code=200)

    return RedirectResponse(url="/admin/dashboard", status_code=303)


# Admin route to assign a volunteer to a BeneficiaryNeed from the admin dashboard
@router.post("/needs/{need_id}/assign-volunteer")
def assign_volunteer_to_need(
    need_id: int,
    request: Request,
    volunteer_id: int = Form(...),
    session: Session = Depends(get_session),
):
    if not verify_staff_session(request):
        raise HTTPException(status_code=401, detail="Unauthorized")

    need = session.get(BeneficiaryNeed, need_id)
    volunteer = session.get(Volunteer, volunteer_id)

    if (
        not need
        or not volunteer
        or need.archived_at is not None
        or volunteer.archived_at is not None
    ):
        raise HTTPException(status_code=404, detail="Need or Volunteer record missing")

    assert need.id is not None
    assert volunteer.id is not None

    match = VolunteerMatch(
        need_id=need.id,
        volunteer_id=volunteer.id,
        matched_by_admin="Admin Direct Match",
    )
    set_need_status(need, NeedStatus.IN_PROGRESS)
    volunteer.status = VolunteerStatus.ASSIGNED

    session.add(match)
    session.add(need)
    session.add(volunteer)
    add_record_history(
        session,
        request,
        "beneficiary_need",
        need_id,
        "volunteer_assigned",
        {"volunteer_id": volunteer_id},
    )
    add_audit_event(
        session,
        request,
        "need.volunteer_assigned",
        "beneficiary_need",
        need_id,
        {"volunteer_id": volunteer_id},
    )
    session.commit()

    if request.headers.get("HX-Request"):
        return Response(status_code=200)

    return RedirectResponse(url="/admin/dashboard", status_code=303)


@router.post("/needs/{need_id}/targets")
def update_community_need_targets(
    need_id: int,
    request: Request,
    target_amount: str = Form(...),
    deadline: str = Form(""),
    session: Session = Depends(get_session),
):
    need = session.get(BeneficiaryNeed, need_id)
    if not need or not need.is_community_need or need.archived_at is not None:
        raise HTTPException(status_code=404, detail="Community need not found.")
    try:
        target = Decimal(target_amount)
    except (InvalidOperation, ValueError) as exc:
        raise HTTPException(status_code=400, detail="Invalid target amount.") from exc
    if not target.is_finite() or target < Decimal("0.00"):
        raise HTTPException(
            status_code=400, detail="Target amount must be zero or greater."
        )
    if not _has_cent_precision(target):
        raise HTTPException(
            status_code=400, detail="Target amount may have at most two decimals."
        )
    try:
        parsed_deadline = datetime.fromisoformat(deadline) if deadline.strip() else None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid need deadline.") from exc
    if parsed_deadline and parsed_deadline.tzinfo is None:
        parsed_deadline = parsed_deadline.replace(tzinfo=timezone.utc)
    old_target = need.target_amount
    old_deadline = need.deadline
    old_status = getattr(need.status, "value", need.status)
    need.target_amount = target
    need.deadline = parsed_deadline
    if target > Decimal("0.00"):
        current = need.current_amount or Decimal("0.00")
        if current >= target:
            set_need_status(need, NeedStatus.FULFILLED)
        elif current > Decimal("0.00") and need.status != NeedStatus.REJECTED:
            set_need_status(need, NeedStatus.IN_PROGRESS)
        elif current == Decimal("0.00") and need.status == NeedStatus.FULFILLED:
            set_need_status(need, NeedStatus.PENDING)
    session.add(need)
    add_record_history(
        session,
        request,
        "beneficiary_need",
        need_id,
        "target_or_deadline_updated",
        {
            "target_from": str(old_target),
            "target_to": str(target),
            "deadline_from": old_deadline.isoformat() if old_deadline else None,
            "deadline_to": parsed_deadline.isoformat() if parsed_deadline else None,
            "status_from": old_status,
            "status_to": getattr(need.status, "value", need.status),
        },
    )
    add_audit_event(
        session,
        request,
        "need.target_or_deadline_updated",
        "beneficiary_need",
        need_id,
    )
    session.commit()
    return RedirectResponse(url="/admin/dashboard?tab=needs", status_code=303)
