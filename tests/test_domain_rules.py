import unittest
from datetime import datetime, timezone

from app.models.entities import (
    BeneficiaryNeed,
    Donation,
    NeedStatus,
    UserRole,
    set_need_status,
)
from app.retention import (
    _is_donation_expired,
    _subtract_years,
    _tax_year_retention_end,
)
from app.security import role_has_permission


class DomainRuleTests(unittest.TestCase):
    def test_role_permissions_allow_only_explicit_actions(self):
        self.assertTrue(role_has_permission(UserRole.CASE_WORKER, "needs.write"))
        self.assertFalse(role_has_permission(UserRole.CASE_WORKER, "donations.write"))
        self.assertFalse(role_has_permission(UserRole.USER, "dashboard"))

    def test_terminal_need_status_sets_and_reopening_clears_closed_date(self):
        need = BeneficiaryNeed(
            contact_name="Member",
            contact_phone="",
            full_address="",
            anonymised_title="Food assistance request",
            area="Kuils River",
            category="Food",
        )

        set_need_status(need, NeedStatus.FULFILLED)
        self.assertIsNotNone(need.closed_at)

        set_need_status(need, NeedStatus.IN_PROGRESS)
        self.assertIsNone(need.closed_at)
        self.assertEqual(need.status, NeedStatus.IN_PROGRESS)

    def test_tax_year_retention_handles_financial_year_and_leap_year(self):
        self.assertEqual(
            _tax_year_retention_end(datetime(2020, 3, 1).date()).isoformat(),
            "2021-02-28",
        )
        self.assertEqual(
            _tax_year_retention_end(datetime(2023, 3, 1).date()).isoformat(),
            "2024-02-29",
        )
        self.assertEqual(
            _subtract_years(datetime(2024, 2, 29, tzinfo=timezone.utc), 1),
            datetime(2023, 2, 28, tzinfo=timezone.utc),
        )

    def test_donation_expires_after_five_full_tax_years(self):
        donation = Donation(
            donor_name="Test donor",
            created_at=datetime(2020, 3, 1, tzinfo=timezone.utc),
        )
        self.assertFalse(_is_donation_expired(donation, datetime(2026, 2, 28).date()))
        self.assertTrue(_is_donation_expired(donation, datetime(2026, 3, 1).date()))
