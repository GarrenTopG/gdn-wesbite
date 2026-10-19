import hashlib
import os
import secrets
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from sqlalchemy.exc import SQLAlchemyError

os.environ.setdefault("APP_SECRET_KEY", "test-mobile-api-key-not-for-production-000000")
os.environ["DATABASE_BACKEND"] = "sqlite"
os.environ["SQLITE_FILE_NAME"] = "mobile_api_test_unused.db"

from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

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
from main import app


class MobileApiTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        SQLModel.metadata.create_all(self.engine)

        def get_test_session():
            with Session(self.engine) as session:
                yield session

        app.dependency_overrides[get_session] = get_test_session
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()
        app.dependency_overrides.clear()
        self.engine.dispose()

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
            "https://aurorahcan.org.za",
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

        app.dependency_overrides[get_session] = failing_session
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
                        content="Public story",
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
            },
        )
        self.assertEqual(needs[0]["title"], "Food support")
        self.assertNotIn("contact_name", needs[0])
        news = self.client.get("/api/news").json()
        self.assertEqual(
            set(news[0]),
            {"id", "title", "summary", "timestamp", "category"},
        )
        self.assertEqual([article["title"] for article in news], ["Published update"])

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
            self.assertEqual(saved_donation.payment_method, "Pledge - No Online Payment")
            self.assertEqual(saved_donation.status, "Submitted")

    def test_google_sign_in_fails_clearly_without_server_configuration(self):
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
