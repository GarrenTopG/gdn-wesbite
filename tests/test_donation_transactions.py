from unittest.mock import patch

from starlette.requests import Request
from sqlmodel import Session, select

from tests.support import DatabaseTestCase
from app.models.entities import Donation, RecordHistory
from app.services.donations import create_donation_with_history


class DonationTransactionTests(DatabaseTestCase):
    def test_donation_is_rolled_back_when_history_write_fails(self):
        request = Request(
            {"type": "http", "method": "POST", "path": "/donate", "headers": []}
        )
        with Session(self.engine) as session:
            with patch(
                "app.services.donations.add_record_history",
                side_effect=RuntimeError("history insert failed"),
            ):
                with self.assertRaisesRegex(RuntimeError, "history insert failed"):
                    with session.begin():
                        create_donation_with_history(
                            session,
                            request,
                            Donation(donor_name="Test donor"),
                            tax_receipt_requested=False,
                        )

        with Session(self.engine) as session:
            self.assertEqual(
                len(session.exec(select(Donation)).all()),
                0,
            )
            self.assertEqual(
                len(session.exec(select(RecordHistory)).all()),
                0,
            )
