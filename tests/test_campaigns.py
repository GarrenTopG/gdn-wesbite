from datetime import date
from decimal import Decimal
from io import BytesIO
import unittest
from unittest.mock import patch

from sqlmodel import Session, select

from app.models.entities import (
    Campaign,
    CampaignStatus,
    Donation,
    DonationStatus,
    User,
    UserNotification,
    UserRole,
)
from tests.support import DatabaseTestCase


class CampaignWebTests(DatabaseTestCase):
    def setUp(self):
        super().setUp()
        self.client.get("/account/login")
        self.csrf_token = self.client.cookies.get("csrf_token", "")

    def create_campaign(
        self,
        *,
        title="Winter support campaign",
        slug="winter-support",
        status=CampaignStatus.PUBLISHED,
        target=Decimal("100.00"),
        deadline=None,
    ):
        with Session(self.engine) as session:
            campaign = Campaign(
                title=title,
                slug=slug,
                summary=f"Help with {title.lower()}.",
                story="A staff-created public campaign story.",
                area="Kuils River",
                category="Community support",
                target_amount=target,
                status=status,
                deadline=deadline,
            )
            session.add(campaign)
            session.commit()
            session.refresh(campaign)
            return campaign.id

    def create_public_user(self, name="Campaign Donor", email="donor@example.org"):
        user = User(
            full_name=name,
            email=email,
            hashed_password="not-used-in-this-test",
            role=UserRole.USER,
        )
        self.authenticate_public(user)
        with Session(self.engine) as session:
            return session.exec(select(User).where(User.email == email)).one().id

    def create_admin(self):
        admin = User(
            full_name="Campaign Admin",
            email="campaign-admin@example.org",
            hashed_password="not-used-in-this-test",
            role=UserRole.ADMINISTRATOR,
        )
        self.authenticate_staff(admin)
        return admin

    def test_donate_page_lists_needs_without_removing_campaign_details(self):
        self.create_campaign(
            title="Active campaign", slug="active", status=CampaignStatus.PUBLISHED
        )
        self.create_campaign(
            title="Draft campaign", slug="draft", status=CampaignStatus.DRAFT
        )

        response = self.client.get("/donate")

        self.assertEqual(response.status_code, 200, response.text)
        self.assertNotIn("Active campaign", response.text)
        self.assertNotIn("Draft campaign", response.text)
        self.assertNotIn("Current campaigns", response.text)
        detail = self.client.get("/campaigns/active")
        self.assertEqual(detail.status_code, 200, detail.text)
        self.assertIn("Active campaign", detail.text)

    def test_contribution_requires_login_and_public_campaign_page_hides_draft(self):
        campaign_id = self.create_campaign()
        self.create_campaign(
            title="Private draft", slug="private-draft", status=CampaignStatus.DRAFT
        )

        detail = self.client.get("/campaigns/winter-support")
        self.assertEqual(detail.status_code, 200, detail.text)
        self.assertIn("Sign in to continue", detail.text)
        self.assertEqual(self.client.get("/campaigns/private-draft").status_code, 404)

        response = self.client.post(
            "/campaigns/winter-support/contribute",
            data={
                "csrf_token": self.csrf_token,
                "amount": "50.00",
                "demo_consent": "true",
            },
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303)
        self.assertIn("/account/login?next_path=", response.headers["location"])
        with Session(self.engine) as session:
            self.assertEqual(
                session.exec(
                    select(Donation).where(Donation.campaign_id == campaign_id)
                ).all(),
                [],
            )

    def test_contribution_review_updates_progress_and_private_notifications(self):
        campaign_id = self.create_campaign()
        donor_id = self.create_public_user()
        contribution = self.client.post(
            "/campaigns/winter-support/contribute",
            data={
                "csrf_token": self.csrf_token,
                "amount": "50.00",
                "demo_consent": "true",
                "is_anonymous": "true",
            },
            follow_redirects=False,
        )
        self.assertEqual(contribution.status_code, 303, contribution.text)
        self.assertEqual(
            contribution.headers["location"], "/account/notifications?submitted=1"
        )

        with Session(self.engine) as session:
            donation = session.exec(
                select(Donation).where(Donation.campaign_id == campaign_id)
            ).one()
            pending_notification = session.exec(
                select(UserNotification).where(UserNotification.user_id == donor_id)
            ).one()
            self.assertEqual(donation.status, DonationStatus.PAYMENT_PENDING.value)
            self.assertFalse(donation.is_verified)
            self.assertEqual(donation.user_id, donor_id)
            self.assertEqual(donation.donor_name, "Anonymous Donor")
            self.assertEqual(pending_notification.event_type, "contribution_pending")
            donation_id = donation.id

        notifications = self.client.get("/account/notifications")
        self.assertEqual(notifications.status_code, 200, notifications.text)
        self.assertIn("awaiting admin review", notifications.text)
        campaign_detail = self.client.get("/campaigns/winter-support")
        self.assertIn("R0.00", campaign_detail.text)

        self.create_admin()
        approved = self.client.post(
            f"/admin/donations/{donation_id}/verify",
            data={"csrf_token": self.csrf_token},
            follow_redirects=False,
        )
        self.assertEqual(approved.status_code, 303, approved.text)
        with Session(self.engine) as session:
            donation = session.get(Donation, donation_id)
            campaign = session.get(Campaign, campaign_id)
            self.assertTrue(donation.is_verified)
            self.assertEqual(donation.status, DonationStatus.RECEIVED_VERIFIED.value)
            self.assertEqual(campaign.status, CampaignStatus.PUBLISHED)
            events = session.exec(
                select(UserNotification)
                .where(UserNotification.user_id == donor_id)
                .order_by(UserNotification.id)
            ).all()
            self.assertEqual(
                [event.event_type for event in events],
                ["contribution_pending", "contribution_verified"],
            )

        progress = self.client.get("/campaigns/winter-support")
        self.assertIn("R50.00", progress.text)
        self.assertIn("admin-approved simulated contributions", progress.text)

        self.client.post(
            "/campaigns/winter-support/contribute",
            data={
                "csrf_token": self.csrf_token,
                "amount": "75.00",
                "demo_consent": "true",
            },
            follow_redirects=False,
        )
        with Session(self.engine) as session:
            second_donation = session.exec(
                select(Donation)
                .where(Donation.campaign_id == campaign_id)
                .where(Donation.status == DonationStatus.PAYMENT_PENDING.value)
            ).one()
            second_donation_id = second_donation.id
        self.client.post(
            f"/admin/donations/{second_donation_id}/verify",
            data={"csrf_token": self.csrf_token},
            follow_redirects=False,
        )
        with Session(self.engine) as session:
            campaign = session.get(Campaign, campaign_id)
            self.assertEqual(campaign.status, CampaignStatus.COMPLETED)
        completed_page = self.client.get("/campaigns/winter-support")
        self.assertIn("R125.00", completed_page.text)
        self.assertIn("no longer accepts contributions", completed_page.text)

        rejected_by_goal = self.client.post(
            "/campaigns/winter-support/contribute",
            data={
                "csrf_token": self.csrf_token,
                "amount": "10.00",
                "demo_consent": "true",
            },
            follow_redirects=False,
        )
        self.assertEqual(rejected_by_goal.status_code, 409)

    def test_rejected_contribution_notifies_owner_and_does_not_increase_progress(self):
        campaign_id = self.create_campaign()
        donor_id = self.create_public_user()
        self.client.post(
            "/campaigns/winter-support/contribute",
            data={
                "csrf_token": self.csrf_token,
                "amount": "25.00",
                "demo_consent": "true",
            },
            follow_redirects=False,
        )
        with Session(self.engine) as session:
            donation = session.exec(
                select(Donation).where(Donation.campaign_id == campaign_id)
            ).one()
            donation_id = donation.id
        self.create_admin()

        rejected = self.client.post(
            f"/admin/donations/{donation_id}/reject",
            data={"csrf_token": self.csrf_token, "reason": "Test rejection"},
            follow_redirects=False,
        )
        self.assertEqual(rejected.status_code, 303, rejected.text)
        with Session(self.engine) as session:
            donation = session.get(Donation, donation_id)
            notification = session.exec(
                select(UserNotification).where(
                    UserNotification.user_id == donor_id,
                    UserNotification.event_type == "contribution_rejected",
                )
            ).one()
            self.assertEqual(donation.status, DonationStatus.REJECTED.value)
            self.assertFalse(donation.is_verified)
            self.assertIn("not approved", notification.message)
        detail = self.client.get("/campaigns/winter-support")
        self.assertIn("R0.00", detail.text)

    def test_user_can_only_read_and_mark_their_own_notifications(self):
        campaign_id = self.create_campaign()
        owner_id = self.create_public_user()
        with Session(self.engine) as session:
            session.add(
                UserNotification(
                    user_id=owner_id,
                    campaign_id=campaign_id,
                    event_type="contribution_pending",
                    message="Private contribution update.",
                )
            )
            session.commit()
            notification_id = session.exec(
                select(UserNotification.id).where(UserNotification.user_id == owner_id)
            ).one()

        marked_read = self.client.post(
            "/account/notifications/read",
            data={
                "csrf_token": self.csrf_token,
                "notification_id": notification_id,
            },
            follow_redirects=False,
        )
        self.assertEqual(marked_read.status_code, 303, marked_read.text)
        with Session(self.engine) as session:
            notification = session.get(UserNotification, notification_id)
            self.assertIsNotNone(notification.read_at)

        self.create_public_user(name="Other User", email="other@example.org")
        page = self.client.get("/account/notifications")
        self.assertEqual(page.status_code, 200, page.text)
        self.assertNotIn("Private contribution update.", page.text)
        forbidden = self.client.post(
            "/account/notifications/read",
            data={
                "csrf_token": self.csrf_token,
                "notification_id": notification_id,
            },
        )
        self.assertEqual(forbidden.status_code, 404)

    def test_campaign_status_updates_notify_contributors(self):
        campaign_id = self.create_campaign()
        donor_id = self.create_public_user()
        with Session(self.engine) as session:
            session.add(
                Donation(
                    donor_name="Campaign Donor",
                    amount=Decimal("25.00"),
                    campaign_id=campaign_id,
                    user_id=donor_id,
                    payment_method="Simulated Contribution - No Payment",
                )
            )
            session.commit()
        self.create_admin()

        for status, expected_event in (
            ("Paused", "campaign_paused"),
            ("Published", "campaign_resumed"),
            ("Archived", "campaign_archived"),
        ):
            response = self.client.post(
                f"/admin/campaigns/{campaign_id}/status",
                data={"csrf_token": self.csrf_token, "status": status},
                follow_redirects=False,
            )
            self.assertEqual(response.status_code, 303, response.text)
            with Session(self.engine) as session:
                notification = session.exec(
                    select(UserNotification).where(
                        UserNotification.user_id == donor_id,
                        UserNotification.event_type == expected_event,
                    )
                ).one()
                self.assertIn("campaign", notification.message.lower())

    def test_campaign_simulations_are_separate_from_general_finance_reports(self):
        campaign_id = self.create_campaign()
        donor_id = self.create_public_user()
        with Session(self.engine) as session:
            campaign_contribution = Donation(
                donor_name="Campaign Donor",
                amount=Decimal("45.00"),
                campaign_id=campaign_id,
                user_id=donor_id,
                payment_method="Simulated Contribution - No Payment",
                is_verified=True,
                status=DonationStatus.RECEIVED_VERIFIED.value,
            )
            general_pledge = Donation(
                donor_name="General Donor",
                amount=Decimal("20.00"),
                is_verified=True,
                status=DonationStatus.RECEIVED_VERIFIED.value,
            )
            session.add(campaign_contribution)
            session.add(general_pledge)
            session.commit()
            session.refresh(campaign_contribution)
            session.refresh(general_pledge)
            campaign_donation_id = campaign_contribution.id
            general_donation_id = general_pledge.id
        self.create_admin()

        dashboard = self.client.get("/admin/dashboard?tab=overview")
        self.assertEqual(dashboard.status_code, 200, dashboard.text)
        self.assertIn("Verified general pledges", dashboard.text)
        self.assertIn("R 20.00", dashboard.text)
        self.assertNotIn("R 65.00", dashboard.text)

        reconciliation = self.client.get("/admin/donations/reconciliation.csv")
        self.assertEqual(reconciliation.status_code, 200, reconciliation.text)
        rows = reconciliation.text.splitlines()[1:]
        exported_ids = {int(row.split(",", 1)[0]) for row in rows}
        self.assertIn(general_donation_id, exported_ids)
        self.assertNotIn(campaign_donation_id, exported_ids)

        pdf_donation_ids = []
        with patch(
            "app.routers.admin.adminexports.generate_donations_pdf",
            side_effect=lambda donations: (
                pdf_donation_ids.extend(donation.id for donation in donations)
                or BytesIO()
            ),
        ):
            pdf_response = self.client.get("/admin/donations/export-pdf")
        self.assertEqual(pdf_response.status_code, 200, pdf_response.text)
        self.assertEqual(pdf_donation_ids, [general_donation_id])

    def test_admin_can_create_draft_then_publish_campaign(self):
        self.create_admin()
        created = self.client.post(
            "/admin/campaigns/add",
            data={
                "csrf_token": self.csrf_token,
                "title": "School supplies",
                "summary": "Help equip local learners.",
                "story": "Staff are organizing learning resources.",
                "area": "Kuils River",
                "category": "Education",
                "target_amount": "2500.00",
                "deadline": date.today().isoformat(),
                "image_url": "",
                "image_alt": "",
            },
            follow_redirects=False,
        )
        self.assertEqual(created.status_code, 303, created.text)
        with Session(self.engine) as session:
            campaign = session.exec(
                select(Campaign).where(Campaign.title == "School supplies")
            ).one()
            self.assertEqual(campaign.status, CampaignStatus.DRAFT)
            campaign_id = campaign.id
            slug = campaign.slug

        self.assertNotIn("School supplies", self.client.get("/donate").text)
        published = self.client.post(
            f"/admin/campaigns/{campaign_id}/status",
            data={"csrf_token": self.csrf_token, "status": "Published"},
            follow_redirects=False,
        )
        self.assertEqual(published.status_code, 303, published.text)
        donate_page = self.client.get("/donate")
        self.assertNotIn("School supplies", donate_page.text)
        campaign_page = self.client.get(f"/campaigns/{slug}")
        self.assertEqual(campaign_page.status_code, 200)
        self.assertIn("School supplies", campaign_page.text)


if __name__ == "__main__":
    unittest.main()
