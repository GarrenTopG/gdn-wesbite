from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from sqlmodel import Session, select

from app.models.entities import (
    AuthSession,
    BeneficiaryNeed,
    Donation,
    RateLimitHit,
    ReceiptAccess,
    User,
)
from app.retention import purge_expired_personal_data
from tests.support import DatabaseTestCase


class RetentionWorkflowTests(DatabaseTestCase):
    def test_preview_is_read_only_and_apply_redacts_expired_records(self):
        old_date = datetime.now(timezone.utc) - timedelta(days=365 * 10)
        with Session(self.engine) as session:
            need = BeneficiaryNeed(
                contact_name="Private Person",
                contact_phone="555-0100",
                full_address="1 Private Road",
                anonymised_title="Food assistance request",
                area="Private Area",
                category="Food",
                created_at=old_date,
                closed_at=old_date,
            )
            donation = Donation(
                donor_name="Private Donor",
                donor_email="donor@example.org",
                donor_phone="555-0101",
                tax_id_number="1234567890",
                tax_address="2 Private Road",
                created_at=old_date,
            )
            session.add_all([need, donation])
            session.flush()
            user = User(
                full_name="Expired Session",
                email="expired@example.org",
                hashed_password="not-used-in-this-test",
            )
            session.add(user)
            session.flush()
            session.add(
                ReceiptAccess(
                    donation_id=donation.id,
                    token_hash="expired-receipt-token-hash",
                    expires_at=old_date,
                )
            )
            session.add(
                RateLimitHit(
                    bucket_key="old-bucket", occurred_at=int(old_date.timestamp())
                )
            )
            session.add(
                AuthSession(
                    token_hash="expired-session-token-hash",
                    user_id=user.id,
                    expires_at=old_date,
                )
            )
            session.commit()
            need_id = need.id
            donation_id = donation.id

        with (
            patch("app.retention.engine", self.engine),
            patch("app.retention.validate_database_ready"),
        ):
            self.assertEqual(purge_expired_personal_data(), (1, 1))
            with Session(self.engine) as session:
                unchanged_need = session.get(BeneficiaryNeed, need_id)
                unchanged_donation = session.get(Donation, donation_id)
                self.assertEqual(unchanged_need.contact_name, "Private Person")
                self.assertEqual(unchanged_donation.donor_email, "donor@example.org")
                self.assertEqual(len(session.exec(select(ReceiptAccess)).all()), 1)

            self.assertEqual(purge_expired_personal_data(apply_changes=True), (1, 1))

        with Session(self.engine) as session:
            redacted_need = session.get(BeneficiaryNeed, need_id)
            redacted_donation = session.get(Donation, donation_id)
            self.assertEqual(redacted_need.contact_name, "")
            self.assertEqual(redacted_need.full_address, "")
            self.assertEqual(redacted_need.area, "")
            self.assertEqual(redacted_need.anonymised_title, "Food assistance request")
            self.assertEqual(redacted_donation.donor_name, "Retention-expired donor")
            self.assertIsNone(redacted_donation.donor_email)
            self.assertIsNone(redacted_donation.tax_id_number)
            self.assertEqual(session.exec(select(ReceiptAccess)).all(), [])
            self.assertEqual(session.exec(select(RateLimitHit)).all(), [])
            self.assertEqual(session.exec(select(AuthSession)).all(), [])
