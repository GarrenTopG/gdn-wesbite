from fastapi import Request
from sqlmodel import Session

from app.models.entities import Donation
from app.security import add_record_history


def create_donation_with_history(
    session: Session,
    request: Request,
    donation: Donation,
    *,
    tax_receipt_requested: bool,
) -> None:
    session.add(donation)
    session.flush()
    add_record_history(
        session,
        request,
        "donation",
        donation.id,
        "submitted",
        {
            "status": donation.status,
            "tax_receipt_requested": tax_receipt_requested,
        },
    )
