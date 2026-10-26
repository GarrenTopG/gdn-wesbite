import hashlib
import os
import secrets
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from tests.support import DatabaseTestCase

from sqlalchemy.exc import SQLAlchemyError

from sqlmodel import Session, select

from app.db.session import get_session
from app.models.entities import (
    BeneficiaryNeed,
    AuthSession,
    Donation,
    NeedStatus,
    NeedUrgency,
    NewsArticle,
    NewsStatus,
    VolunteerOffer,
    User,
    UserRole,
)
from app.security import STAFF_COOKIE_NAME


class MobileApiTests(DatabaseTestCase):
    def register(self, email="volunteer@example.org"):
        response = self.client.post(
            "/api/auth/register",
            json={
                "fullName": "Mobile Volunteer",
                "email": email,
                "password": "CorrectHorseBatteryStaple1!",
                "role": "administrator",
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(
            set(response.json()),
            {"success", "message", "token", "user"},
        )
        self.assertEqual(
            set(response.json()["user"]),
            {"userId", "fullName", "email", "role"},
        )
        return response.json()

    def test_cors_allows_emulator_lan_and_production_origins(self):
        for origin in (
            "http://10.0.2.2:8000",
            "http://192.168.1.27:8080",
            "https://aurorah-web-hub.onrender.com",
        ):
            with self.subTest(origin=origin):
                response = self.client.options(
                    "/api/news",
                    headers={
                        "Origin": origin,
                        "Access-Control-Request-Method": "GET",
                        "Access-Control-Request-Headers": "authorization",
                    },
                )
                self.assertEqual(response.status_code, 200)
                self.assertEqual(
                    response.headers["access-control-allow-origin"], origin
                )

        denied = self.client.options(
            "/api/news",
            headers={
                "Origin": "https://untrusted.example",
                "Access-Control-Request-Method": "GET",
            },
        )
        self.assertNotIn("access-control-allow-origin", denied.headers)

    def test_mobile_api_returns_json_when_database_fails(self):
        def failing_session():
            raise SQLAlchemyError("test database unavailable")
            yield

        self.app.dependency_overrides[get_session] = failing_session
        response = self.client.get("/api/news")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(
            response.json(),
            {"detail": "Database temporarily unavailable."},
        )

    def test_registration_login_and_password_change(self):
        account = self.register()
        self.assertEqual(account["user"]["role"], "Volunteer")
        self.assertEqual(
            self.client.post(
                "/api/auth/register",
                json={
                    "fullName": "Duplicate",
                    "email": "volunteer@example.org",
                    "password": "CorrectHorseBatteryStaple1!",
                },
            ).status_code,
            409,
        )

        changed = self.client.post(
            "/api/auth/change-password",
            headers={"Authorization": f"Bearer {account['token']}"},
            json={
                "email": "volunteer@example.org",
                "oldPassword": "CorrectHorseBatteryStaple1!",
                "newPassword": "AnotherCorrectHorseBattery2!",
            },
        )
        self.assertEqual(changed.status_code, 200, changed.text)
        self.assertEqual(
            changed.json(),
            {"success": True, "message": "Password changed."},
        )
        login = self.client.post(
            "/api/auth/login",
            json={
                "email": "volunteer@example.org",
                "password": "AnotherCorrectHorseBattery2!",
            },
        )
        self.assertEqual(login.status_code, 200, login.text)
        self.assertEqual(login.headers["cache-control"], "no-store")

    def test_profile_update_requires_authentication_and_persists_changes(self):
        account = self.register()
        initial_profile = self.client.get("/api/auth/profile")
        self.assertEqual(initial_profile.status_code, 401)
        initial_profile = self.client.get(
            "/api/auth/profile",
            headers={"Authorization": f"Bearer {account['token']}"},
        )
        self.assertEqual(initial_profile.status_code, 200, initial_profile.text)
        self.assertEqual(initial_profile.json()["fullName"], "Mobile Volunteer")

        body = {
            "full_name": "Updated Mobile User",
            "phone_number": "+27 82 123 4567",
            "preferences": {"notifications": True, "language": "en"},
        }

        unauthorized = self.client.put("/api/auth/profile", json=body)
        self.assertEqual(unauthorized.status_code, 401)

        response = self.client.put(
            "/api/auth/profile",
            headers={"Authorization": f"Bearer {account['token']}"},
            json=body,
        )
        self.assertEqual(response.status_code, 200, response.text)
        fetched = self.client.get(
            "/api/auth/profile",
            headers={"Authorization": f"Bearer {account['token']}"},
        )
        self.assertEqual(fetched.status_code, 200, fetched.text)
        self.assertEqual(fetched.json()["fullName"], "Updated Mobile User")
        self.assertEqual(fetched.json()["phoneNumber"], "+27 82 123 4567")
        self.assertEqual(
            response.json(),
            {
                "userId": account["user"]["userId"],
                "fullName": "Updated Mobile User",
                "email": "volunteer@example.org",
                "role": "Volunteer",
                "phoneNumber": "+27 82 123 4567",
                "preferences": {"notifications": True, "language": "en"},
            },
        )
        with Session(self.engine) as session:
            user = session.get(User, account["user"]["userId"])
            self.assertEqual(user.full_name, "Updated Mobile User")
            self.assertEqual(user.phone_number, "+27 82 123 4567")
            self.assertEqual(
                user.preferences, {"notifications": True, "language": "en"}
            )

    def test_logout_revokes_current_mobile_session(self):
        account = self.register()
        headers = {"Authorization": f"Bearer {account['token']}"}

        response = self.client.post("/api/auth/logout", headers=headers)

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), {"success": True, "message": "Signed out."})
        protected = self.client.post(
            "/api/assistance-requests",
            headers=headers,
            json={
                "category": "Food",
                "description": "Need groceries",
                "location": "Kuils River",
                "contactPhone": "+27 82 123 4567",
            },
        )
        self.assertEqual(protected.status_code, 401)
        with Session(self.engine) as session:
            auth_session = session.exec(
                select(AuthSession).where(
                    AuthSession.user_id == account["user"]["userId"]
                )
            ).first()
            self.assertIsNone(auth_session)

    def test_assistance_request_requires_authentication_and_links_account(self):
        account = self.register()
        body = {
            "category": "Food",
            "description": "Need groceries for the week",
            "urgency": "High",
            "location": "Kuils River",
            "contact_phone": "+27 82 123 4567",
        }

        unauthorized = self.client.post("/api/assistance-requests", json=body)
        self.assertEqual(unauthorized.status_code, 401)

        invalid_urgency = self.client.post(
            "/api/assistance-requests",
            headers={"Authorization": "Bearer " + account.get("token", "")},
            json={**body, "urgency": "Urgent"},
        )
        self.assertEqual(invalid_urgency.status_code, 400)
        self.assertEqual(
            invalid_urgency.json(),
            {"detail": "Invalid assistance urgency."},
        )

        response = self.client.post(
            "/api/assistance-requests",
            headers={"Authorization": f"Bearer {account['token']}"},
            json=body,
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["success"], True)
        self.assertIn("needId", response.json())
        with Session(self.engine) as session:
            need = session.get(BeneficiaryNeed, response.json()["needId"])
            self.assertEqual(need.user_id, account["user"]["userId"])
            self.assertEqual(need.contact_name, "Mobile Volunteer")
            self.assertEqual(need.contact_phone, "+27 82 123 4567")
            self.assertEqual(need.category, "Food")
            self.assertEqual(need.request_details, "Need groceries for the week")
            self.assertEqual(need.area, "Kuils River")
            self.assertEqual(need.urgency, NeedUrgency.HIGH)
            self.assertFalse(need.is_community_need)

    def test_mobile_donation_accepts_in_kind_offers(self):
        account = self.register()
        response = self.client.post(
            "/api/donations",
            headers={"Authorization": f"Bearer {account['token']}"},
            json={
                "donation_type": "inkind",
                "item_category": "Blankets & Bedding",
                "item_description": "Three clean blankets",
                "drop_off_option": "dropoff",
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn("in-kind donation offer", response.json()["message"])
        with Session(self.engine) as session:
            donation = session.exec(select(Donation)).one()
            self.assertEqual(donation.donation_type, "inkind")
            self.assertEqual(donation.item_category, "Blankets & Bedding")
            self.assertEqual(donation.item_description, "Three clean blankets")
            self.assertEqual(donation.logistics_type, "dropoff")
            self.assertEqual(donation.amount, 0)

    def test_public_feeds_return_only_public_records(self):
        with Session(self.engine) as session:
            session.add_all(
                [
                    BeneficiaryNeed(
                        contact_name="Private Beneficiary",
                        contact_phone="555-0100",
                        full_address="Private street",
                        anonymised_title="Food support",
                        area="Kuils River",
                        category="Food",
                        urgency=NeedUrgency.HIGH,
                        status=NeedStatus.PENDING,
                        is_community_need=True,
                    ),
                    BeneficiaryNeed(
                        contact_name="Private Beneficiary",
                        contact_phone="555-0100",
                        full_address="Private street",
                        anonymised_title="Private case",
                        area="Private area",
                        category="Health",
                        is_community_need=False,
                    ),
                    NewsArticle(
                        title="Published update",
                        slug="published-update",
                        summary="Public summary",
                        content="First article paragraph.\n\nSecond article paragraph.",
                        image_url="/static/images/news/community-cook-off.png",
                        status=NewsStatus.PUBLISHED.value,
                    ),
                    NewsArticle(
                        title="Draft update",
                        slug="draft-update",
                        summary="Draft summary",
                        content="Draft story",
                        status=NewsStatus.DRAFT.value,
                    ),
                ]
            )
            session.commit()

        needs = self.client.get("/api/needs").json()
        self.assertEqual(len(needs), 1)
        self.assertEqual(
            set(needs[0]),
            {
                "needId",
                "title",
                "description",
                "location",
                "priority",
                "category",
                "status",
                "createdAt",
                "targetAmount",
                "currentAmount",
                "imageUrl",
                "imageAlt",
                "article",
                "articleExcerpt",
                "deadline",
            },
        )
        self.assertEqual(needs[0]["title"], "Food support")
        self.assertNotIn("contact_name", needs[0])
        news = self.client.get("/api/news").json()
        self.assertEqual(
            set(news[0]),
            {
                "id",
                "title",
                "summary",
                "content",
                "image_url",
                "timestamp",
                "category",
            },
        )
        self.assertEqual([article["title"] for article in news], ["Published update"])
        self.assertEqual(
            news[0]["content"], "First article paragraph.\n\nSecond article paragraph."
        )
        self.assertEqual(
            news[0]["image_url"],
            "/static/images/news/community-cook-off.png",
        )

    def test_mobile_needs_feed_aligns_with_website_donate_page(self):
        now = datetime.now(timezone.utc)
        yesterday = now - timedelta(days=2)
        tomorrow = now + timedelta(days=2)

        with Session(self.engine) as session:
            # Need 1: Active community need, no deadline (latest)
            n1 = BeneficiaryNeed(
                contact_name="Internal",
                contact_phone="555-0100",
                full_address="1 Main St",
                anonymised_title="Active Need No Deadline",
                area="Kuils River",
                category="Food",
                urgency=NeedUrgency.HIGH,
                status=NeedStatus.PENDING,
                is_community_need=True,
                target_amount=1000.0,
                current_amount=250.0,
                article="Full article story for Need 1.",
                image_url="/static/images/need1.jpg",
                image_alt="Need 1 Image",
                created_at=now,
            )
            # Need 2: Active community need, future deadline
            n2 = BeneficiaryNeed(
                contact_name="Internal",
                contact_phone="555-0100",
                full_address="1 Main St",
                anonymised_title="Active Need Future Deadline",
                area="Sunbird Park",
                category="Education",
                urgency=NeedUrgency.MEDIUM,
                status=NeedStatus.IN_PROGRESS,
                is_community_need=True,
                deadline=tomorrow,
                target_amount=5000.0,
                current_amount=1200.0,
                article="Full article story for Need 2.",
                created_at=now - timedelta(hours=1),
            )
            # Need 3: Fulfilled community need, future deadline (included by both)
            n3 = BeneficiaryNeed(
                contact_name="Internal",
                contact_phone="555-0100",
                full_address="1 Main St",
                anonymised_title="Fulfilled Need Future Deadline",
                area="Kuils River",
                category="Health",
                urgency=NeedUrgency.LOW,
                status=NeedStatus.FULFILLED,
                is_community_need=True,
                deadline=tomorrow,
                created_at=now - timedelta(hours=2),
            )
            # Need 4: Past deadline (excluded by both)
            n4 = BeneficiaryNeed(
                contact_name="Internal",
                contact_phone="555-0100",
                full_address="1 Main St",
                anonymised_title="Expired Need",
                area="Kuils River",
                category="Food",
                urgency=NeedUrgency.CRITICAL,
                status=NeedStatus.PENDING,
                is_community_need=True,
                deadline=yesterday,
                created_at=now - timedelta(hours=3),
            )
            # Need 5: Rejected need (excluded by both)
            n5 = BeneficiaryNeed(
                contact_name="Internal",
                contact_phone="555-0100",
                full_address="1 Main St",
                anonymised_title="Rejected Need",
                area="Kuils River",
                category="Other",
                urgency=NeedUrgency.LOW,
                status=NeedStatus.REJECTED,
                is_community_need=True,
                created_at=now - timedelta(hours=4),
            )
            # Need 6: Archived need (excluded by both)
            n6 = BeneficiaryNeed(
                contact_name="Internal",
                contact_phone="555-0100",
                full_address="1 Main St",
                anonymised_title="Archived Need",
                area="Kuils River",
                category="Other",
                urgency=NeedUrgency.LOW,
                status=NeedStatus.PENDING,
                is_community_need=True,
                archived_at=now,
                created_at=now - timedelta(hours=5),
            )
            # Need 7: Private/non-community need (excluded by both)
            n7 = BeneficiaryNeed(
                contact_name="Private Beneficiary",
                contact_phone="555-0100",
                full_address="1 Main St",
                anonymised_title="Private Need",
                area="Private",
                category="Food",
                urgency=NeedUrgency.HIGH,
                status=NeedStatus.PENDING,
                is_community_need=False,
                created_at=now - timedelta(hours=6),
            )
            session.add_all([n1, n2, n3, n4, n5, n6, n7])
            session.commit()
            session.refresh(n1)
            session.refresh(n2)
            session.refresh(n3)
            expected_ids = [n1.id, n2.id, n3.id]

        # Call Mobile API /api/needs
        api_response = self.client.get("/api/needs")
        self.assertEqual(api_response.status_code, 200)
        api_needs = api_response.json()
        api_need_ids = [item["needId"] for item in api_needs]

        # Fetch Website /donate page
        web_response = self.client.get("/donate")
        self.assertEqual(web_response.status_code, 200)
        web_html = web_response.text

        # Both website and mobile API show exact same need IDs in same order
        self.assertEqual(api_need_ids, expected_ids)
        for need_id in expected_ids:
            self.assertIn(f"/community-needs/{need_id}", web_html)
        self.assertNotIn("Expired Need", web_html)
        self.assertNotIn("Rejected Need", web_html)
        self.assertNotIn("Archived Need", web_html)

        # Check returned real database values for n1 in API response
        n1_data = api_needs[0]
        self.assertEqual(n1_data["title"], "Active Need No Deadline")
        self.assertEqual(n1_data["location"], "Kuils River")
        self.assertEqual(n1_data["category"], "Food")
        self.assertEqual(n1_data["priority"], "High")
        self.assertEqual(float(n1_data["targetAmount"]), 1000.0)
        self.assertEqual(float(n1_data["currentAmount"]), 250.0)
        self.assertEqual(n1_data["imageUrl"], "/static/images/need1.jpg")
        self.assertEqual(n1_data["imageAlt"], "Need 1 Image")
        self.assertEqual(n1_data["article"], "Full article story for Need 1.")
        self.assertEqual(n1_data["articleExcerpt"], "Full article story for Need 1.")

    def test_offers_and_donations_require_the_account_identity(self):
        account = self.register()
        with Session(self.engine) as session:
            need = BeneficiaryNeed(
                contact_name="Internal",
                contact_phone="",
                full_address="",
                anonymised_title="Community garden",
                area="Kuils River",
                category="Food",
                is_community_need=True,
            )
            session.add(need)
            session.commit()
            session.refresh(need)
            need_id = need.id

        headers = {"Authorization": f"Bearer {account['token']}"}
        mismatch = self.client.post(
            "/api/needs/offer-assistance",
            headers=headers,
            json={
                "needId": need_id,
                "userEmail": "other@example.org",
                "volunteerSkill": "Gardening",
                "notes": "Weekends",
            },
        )
        self.assertEqual(mismatch.status_code, 403)
        offer = self.client.post(
            "/api/needs/offer-assistance",
            headers=headers,
            json={
                "needId": need_id,
                "userEmail": "volunteer@example.org",
                "volunteerSkill": "Gardening",
                "notes": "Weekends",
            },
        )
        self.assertEqual(offer.status_code, 200, offer.text)
        self.assertEqual(
            offer.json(),
            {
                "success": True,
                "message": "Your offer to help has been submitted.",
            },
        )

        donation = self.client.post(
            "/api/donations",
            headers=headers,
            json={
                "category": "General Fund",
                "amount": "25.50",
                "paymentMethod": "Card",
                "userEmail": "volunteer@example.org",
            },
        )
        self.assertEqual(donation.status_code, 200, donation.text)
        self.assertEqual(
            set(donation.json()),
            {"success", "transactionRef", "message"},
        )
        self.assertIn("No payment was processed", donation.json()["message"])
        with Session(self.engine) as session:
            self.assertEqual(len(session.exec(select(VolunteerOffer)).all()), 1)
            saved_donation = session.exec(select(Donation)).one()
            self.assertEqual(
                saved_donation.payment_method, "Pledge - No Online Payment"
            )
            self.assertEqual(saved_donation.status, "Submitted")

    def test_legacy_google_sign_in_fails_clearly_without_server_configuration(self):
        with patch.dict(os.environ, {"FIREBASE_PROJECT_ID": ""}):
            response = self.client.post(
                "/api/auth/google-sso",
                json={"idToken": "not-a-real-token"},
            )
        self.assertEqual(response.status_code, 503)

    def test_staff_can_review_mobile_offers_from_needs_dashboard(self):
        with Session(self.engine) as session:
            applicant = User(
                full_name="Mobile Volunteer",
                email="volunteer@example.org",
                hashed_password="unused",
                role=UserRole.USER,
            )
            staff = User(
                full_name="Case Worker",
                email="caseworker@example.org",
                hashed_password="unused",
                role=UserRole.CASE_WORKER,
            )
            need = BeneficiaryNeed(
                contact_name="Internal",
                contact_phone="",
                full_address="",
                anonymised_title="Community garden",
                area="Kuils River",
                category="Food",
                is_community_need=True,
            )
            session.add_all([applicant, staff, need])
            session.flush()
            offer = VolunteerOffer(
                need_id=need.id,
                user_id=applicant.id,
                volunteer_skill="Gardening",
            )
            session.add(offer)
            session.flush()
            offer_id = offer.id
            staff_token = secrets.token_urlsafe(32)
            session.add(
                AuthSession(
                    token_hash=hashlib.sha256(staff_token.encode()).hexdigest(),
                    user_id=staff.id,
                    expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
                    mfa_verified=True,
                )
            )
            session.commit()

        self.client.cookies.set(STAFF_COOKIE_NAME, staff_token)
        dashboard = self.client.get("/admin/dashboard?tab=needs")
        self.assertEqual(dashboard.status_code, 200, dashboard.text)
        self.assertIn("volunteer@example.org", dashboard.text)

        csrf_token = self.client.cookies.get("csrf_token")
        reviewed = self.client.post(
            f"/admin/needs/offers/{offer_id}/review",
            headers={"X-CSRF-Token": csrf_token},
            follow_redirects=False,
        )
        self.assertEqual(reviewed.status_code, 303, reviewed.text)
        with Session(self.engine) as session:
            self.assertEqual(session.get(VolunteerOffer, offer_id).status, "Reviewed")


if __name__ == "__main__":
    unittest.main()
