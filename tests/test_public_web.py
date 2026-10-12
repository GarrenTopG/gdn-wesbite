import os
import re
import unittest

os.environ.setdefault("APP_SECRET_KEY", "test-public-web-key-not-for-production-000000")
os.environ["DATABASE_BACKEND"] = "sqlite"
os.environ["SQLITE_FILE_NAME"] = "public_web_test_unused.db"

from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.db.session import get_session
from app.models.entities import Donation, DonationStatus, User, UserRole
from app.manage_staff import hash_password
from main import app


class PublicWebTests(unittest.TestCase):
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

    def csrf_token(self):
        response = self.client.get("/account/login")
        self.assertEqual(response.status_code, 200, response.text)
        token = self.client.cookies.get("csrf_token")
        self.assertTrue(token)
        return token

    def test_account_creation_gates_assistance_and_volunteering(self):
        for path in ("/requestassistance", "/volunteer"):
            response = self.client.get(path, follow_redirects=False)
            self.assertEqual(response.status_code, 303)
            self.assertIn("/account/login?next_path=", response.headers["location"])

        response = self.client.post(
            "/account/register",
            data={
                "csrf_token": self.csrf_token(),
                "full_name": "Community Member",
                "email": "member@example.org",
                "password": "CorrectHorseBatteryStaple1!",
                "password_confirm": "CorrectHorseBatteryStaple1!",
                "next_path": "/requestassistance",
            },
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303, response.text)
        self.assertEqual(response.headers["location"], "/requestassistance")
        self.assertTrue(self.client.cookies.get("user_session"))
        with Session(self.engine) as session:
            user = session.exec(
                select(User).where(User.email == "member@example.org")
            ).one()
        self.assertEqual(user.role, UserRole.USER)
        about = self.client.get("/about")
        self.assertIn('class="account-avatar" aria-hidden="true">CM</span>', about.text)
        self.assertIn("Sign out", about.text)
        self.assertEqual(self.client.get("/requestassistance").status_code, 200)
        self.assertEqual(self.client.get("/volunteer").status_code, 200)

        token = self.client.cookies.get("csrf_token")
        logout = self.client.post(
            "/account/logout",
            data={"csrf_token": token},
            follow_redirects=False,
        )
        self.assertEqual(logout.status_code, 303)
        self.assertFalse(self.client.cookies.get("user_session"))
        login = self.client.post(
            "/account/login",
            data={
                "csrf_token": token,
                "email": "MEMBER@example.org",
                "password": "CorrectHorseBatteryStaple1!",
                "next_path": "/volunteer",
            },
            follow_redirects=False,
        )
        self.assertEqual(login.status_code, 303, login.text)
        self.assertEqual(login.headers["location"], "/volunteer")
        self.assertTrue(self.client.cookies.get("user_session"))

    def test_guest_can_submit_donation_without_email(self):
        token = self.csrf_token()
        response = self.client.post(
            "/donate",
            data={
                "csrf_token": token,
                "donation_type": "monetary",
                "amount": "50.00",
                "need_id": "food_relief",
                "popia": "true",
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn("Your pledge has been recorded", response.text)
        with Session(self.engine) as session:
            donation = session.exec(select(Donation)).one()
        self.assertIsNone(donation.donor_email)
        self.assertEqual(donation.cause, "Food relief")

    def test_donation_validation_returns_a_human_readable_page(self):
        response = self.client.post(
            "/donate",
            data={
                "csrf_token": self.csrf_token(),
                "donation_type": "monetary",
                "amount": "50.00",
                "request_tax_certificate": "true",
                "donor_name": "Donor Name",
                "popia": "true",
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("We could not submit this pledge.", response.text)
        self.assertIn("Email is optional for a regular pledge.", response.text)
        self.assertIn('value="Donor Name"', response.text)
        self.assertNotIn('"detail":', response.text)

    def test_expired_admin_page_session_redirects_to_staff_login(self):
        response = self.client.get(
            "/admin/dashboard",
            headers={"accept": "text/html"},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/admin/login")

    def test_staff_session_cookie_matches_server_session_lifetime(self):
        with Session(self.engine) as session:
            session.add(
                User(
                    full_name="Administrator",
                    email="admin@example.org",
                    hashed_password=hash_password("CorrectHorseBatteryStaple1!"),
                    role=UserRole.ADMINISTRATOR,
                )
            )
            session.add(
                Donation(
                    donor_name="Pending donor",
                    status=DonationStatus.SUBMITTED.value,
                )
            )
            session.commit()

        response = self.client.post(
            "/admin/login",
            data={
                "csrf_token": self.csrf_token(),
                "email": "admin@example.org",
                "password": "CorrectHorseBatteryStaple1!",
            },
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303, response.text)
        self.assertIn("max-age=43200", response.headers["set-cookie"].lower())
        dashboard = self.client.get("/admin/dashboard")
        self.assertEqual(dashboard.status_code, 200, dashboard.text[:1000])
        self.assertIn("id=\"notifications-panel\"", dashboard.text)
        self.assertIn("Donation pledges to review", dashboard.text)
        self.assertRegex(
            dashboard.text,
            r'class="admin-header-icon-badge" id="notifications-badge"[^>]*>1</span>',
        )
        self.assertIn('class="admin-user-initials" aria-hidden="true">A</span>', dashboard.text)
        self.assertIn('class="admin-user-role-pill">Administration</span>', dashboard.text)
        donation_notification = re.search(
            r'data-notification-key="donations".*?data-notification-fingerprint="([0-9a-f]{64})"',
            dashboard.text,
            re.DOTALL,
        )
        self.assertIsNotNone(donation_notification)
        read_response = self.client.post(
            "/admin/notifications/read",
            data={
                "notification_key": "donations",
                "fingerprint": donation_notification.group(1),
            },
            headers={"X-CSRF-Token": self.client.cookies.get("csrf_token", "")},
        )
        self.assertEqual(read_response.status_code, 200, read_response.text)
        read_dashboard = self.client.get("/admin/dashboard")
        self.assertIn('data-notification-read="true"', read_dashboard.text)
        self.assertRegex(
            read_dashboard.text,
            r'class="admin-header-icon-badge hidden" id="notifications-badge"[^>]*>0</span>',
        )
        with Session(self.engine) as session:
            session.add(
                Donation(
                    donor_name="Another pending donor",
                    status=DonationStatus.SUBMITTED.value,
                )
            )
            session.commit()
        updated_dashboard = self.client.get("/admin/dashboard")
        self.assertRegex(
            updated_dashboard.text,
            r'class="admin-header-icon-badge" id="notifications-badge"[^>]*>2</span>',
        )
        security = self.client.get("/admin/security")
        self.assertEqual(security.status_code, 200, security.text[:1000])
        self.assertIn("class=\"admin-workspace\"", security.text)

    def test_public_browse_pages_render(self):
        for path in ("/", "/about", "/donate", "/account/register"):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200, f"{path}: {response.text[:500]}")
        about = self.client.get("/about")
        self.assertIn("Latifah Jacobs", about.text)
        self.assertIn("tel:+27715893409", about.text)
        self.assertIn("mailto:latifahjacobm@gmail.com", about.text)
        self.assertIn(
            "https://cdn.24.co.za/files/Cms/General/d/8285/020dda8f2e224d6d8fe438177cfad1bb.jpg",
            about.text,
        )
        self.assertIn("/static/images/aurora-public-library.webp", about.text)
        self.assertIn("Come say hello", about.text)
        library_photo = self.client.get("/static/images/aurora-public-library.webp")
        self.assertEqual(library_photo.status_code, 200)
        self.assertEqual(library_photo.headers["content-type"], "image/webp")


if __name__ == "__main__":
    unittest.main()
