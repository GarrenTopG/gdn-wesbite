import argparse
import calendar
from datetime import date, datetime, timezone

from sqlmodel import Session, select

from app.db.session import create_db_and_tables, engine
from app.models.entities import (
    AuthSession,
    BeneficiaryNeed,
    Donation,
    RateLimitHit,
    ReceiptAccess,
)


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def _subtract_years(value: datetime, years: int) -> datetime:
    year = value.year - years
    day = min(value.day, calendar.monthrange(year, value.month)[1])
    return value.replace(year=year, day=day)


def _tax_year_retention_end(donation_date: date) -> date:
    if donation_date.month >= 3:
        year = donation_date.year + 1
    else:
        year = donation_date.year
    return date(year, 2, calendar.monthrange(year, 2)[1])


def _is_donation_expired(donation: Donation, today: date) -> bool:
    tax_year_end = _tax_year_retention_end(_as_utc(donation.created_at).date())
    retention_end_year = tax_year_end.year + 5
    retention_end = date(
        retention_end_year,
        tax_year_end.month,
        min(
            tax_year_end.day,
            calendar.monthrange(retention_end_year, tax_year_end.month)[1],
        ),
    )
    return today > retention_end


def purge_expired_personal_data(apply_changes: bool = False) -> tuple[int, int]:
    now = datetime.now(timezone.utc)
    beneficiary_cutoff = _subtract_years(now, 2)
    purged_beneficiaries = 0
    purged_donations = 0

    create_db_and_tables()
    with Session(engine) as session:
        needs = session.exec(select(BeneficiaryNeed)).all()
        donations = session.exec(select(Donation)).all()
        all_receipts = session.exec(select(ReceiptAccess)).all()
        expired_receipts = [
            receipt
            for receipt in all_receipts
            if _as_utc(receipt.expires_at) < now
        ]
        expired_sessions = session.exec(select(AuthSession)).all()
        expired_sessions = [
            auth_session
            for auth_session in expired_sessions
            if _as_utc(auth_session.expires_at) < now
        ]

        for need in needs:
            if need.is_community_need:
                continue
            retention_start = _as_utc(need.closed_at or need.created_at)
            if retention_start <= beneficiary_cutoff:
                purged_beneficiaries += 1
                if apply_changes:
                    need.contact_name = ""
                    need.contact_phone = ""
                    need.full_address = ""
                    need.anonymised_title = f"{need.category} assistance request"
                    need.area = ""
                    session.add(need)

        expired_donation_ids = set()
        for donation in donations:
            if _is_donation_expired(donation, now.date()):
                purged_donations += 1
                if apply_changes:
                    donation.donor_name = "Retention-expired donor"
                    donation.cause = "Retained donation record"
                    donation.donor_email = None
                    donation.donor_phone = None
                    donation.tax_id_number = None
                    donation.tax_address = None
                    donation.pending_receipt_token_hash = None
                    donation.pickup_address = None
                    donation.item_description = None
                    donation.message = None
                    donation.proof_of_payment_url = None
                    session.add(donation)
                    if donation.id is not None:
                        expired_donation_ids.add(donation.id)

        if apply_changes:
            for receipt in expired_receipts:
                session.delete(receipt)
            for auth_session in expired_sessions:
                session.delete(auth_session)
            session.exec(
                RateLimitHit.__table__.delete().where(
                    RateLimitHit.occurred_at < int(now.timestamp()) - 86400
                )
            )
            if expired_donation_ids:
                stale_access = session.exec(
                    select(ReceiptAccess).where(
                        ReceiptAccess.donation_id.in_(expired_donation_ids)
                    )
                ).all()
                for receipt in stale_access:
                    session.delete(receipt)
            session.commit()

    return purged_beneficiaries, purged_donations


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Preview or apply the configured personal-data retention policy."
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Redact expired personal data. Without this flag, only report counts.",
    )
    args = parser.parse_args()
    beneficiary_count, donation_count = purge_expired_personal_data(args.apply)
    action = "Redacted" if args.apply else "Would redact"
    print(
        f"{action} personal data for {beneficiary_count} beneficiary records "
        f"and {donation_count} donation records."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
