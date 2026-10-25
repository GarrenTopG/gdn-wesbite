import hashlib
import re
import unittest
from datetime import datetime, timedelta, timezone

from tests.support import DatabaseTestCase, totp_code

from sqlalchemy import text
from sqlalchemy import true
from sqlmodel import Session, select

from sqlalchemy.dialects import mssql
from app.models.entities import (
    AuthSession,
    BeneficiaryNeed,
    Donation,
    DonationStatus,
    NeedStatus,
    NewsArticle,
    ReceiptAccess,
    RecordHistory,
    User,
    UserRole,
    Volunteer,
    VolunteerStatus,
)
from app.manage_staff import hash_password
from app.security import STAFF_COOKIE_NAME
from app.routers.donations import (
    _public_campaigns_statement,
    _public_community_needs_statement,
)
from tests.migration_support import (
    normalize_user_roles as _normalize_user_roles,
    normalize_volunteer_available_days as _normalize_volunteer_available_days,
    normalize_volunteer_status as _normalize_volunteer_status,
)


class PublicWebTests(DatabaseTestCase):
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
        self.assertFalse(self.client.cookies.get(STAFF_COOKIE_NAME))
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

    def test_assistance_form_rejects_invalid_urgency_and_records_history(self):
        csrf_token = self.csrf_token()
        registration = self.client.post(
            "/account/register",
            data={
                "csrf_token": csrf_token,
                "full_name": "Assistance Applicant",
                "email": "applicant@example.org",
                "password": "CorrectHorseBatteryStaple1!",
                "password_confirm": "CorrectHorseBatteryStaple1!",
            },
            follow_redirects=False,
        )
        self.assertEqual(registration.status_code, 303)

        form_data = {
            "first_name": "Assistance",
            "last_name": "Applicant",
            "phone": "82 123 4567",
            "location": "Kuils River",
            "need_type": "Food Parcel",
            "description": "Need groceries for this week.",
            "popia": "true",
        }
        missing_csrf = self.client.post(
            "/requestassistance",
            data={**form_data, "urgency": "High"},
        )
        self.assertEqual(missing_csrf.status_code, 403)

        invalid_urgency = self.client.post(
            "/requestassistance",
            data={**form_data, "csrf_token": csrf_token, "urgency": "Urgent"},
        )
        self.assertEqual(invalid_urgency.status_code, 400)
        self.assertEqual(
            invalid_urgency.json(),
            {"detail": "Invalid assistance urgency."},
        )
        with Session(self.engine) as session:
            self.assertEqual(session.exec(select(BeneficiaryNeed)).all(), [])

        submitted = self.client.post(
            "/requestassistance",
            data={**form_data, "csrf_token": csrf_token, "urgency": "Critical"},
        )
        self.assertEqual(submitted.status_code, 200, submitted.text)
        with Session(self.engine) as session:
            need = session.exec(select(BeneficiaryNeed)).one()
            history = session.exec(
                select(RecordHistory).where(
                    RecordHistory.record_type == "beneficiary_need",
                    RecordHistory.record_id == need.id,
                )
            ).one()
        self.assertEqual(need.urgency.value, "Critical")
        self.assertEqual(history.action, "submitted")
        self.assertEqual(history.record_id, need.id)

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

    def test_demo_tax_certificate_is_available_without_payment_verification(self):
        csrf = self.csrf_token()
        pledge_response = self.client.post(
            "/donate",
            data={
                "csrf_token": csrf,
                "donation_type": "monetary",
                "amount": "50.00",
                "request_tax_certificate": "true",
                "tax_id_number": "1234567890",
                "tax_address": "1 Example Road",
                "donor_name": "Receipt Donor",
                "donor_email": "donor@example.org",
                "popia": "true",
            },
        )
        self.assertEqual(pledge_response.status_code, 200, pledge_response.text)
        self.assertIn("Your sample certificate is ready", pledge_response.text)
        self.assertIn('id="demo-receipt-download"', pledge_response.text)
        token_match = re.search(
            r'name="receipt_token" value="([^"]+)"', pledge_response.text
        )
        if token_match is None:
            self.fail("The donation confirmation did not include a receipt token.")
        token = token_match.group(1)

        response = self.client.post(
            "/donate/tax-certificate",
            data={"csrf_token": csrf, "receipt_token": token},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "application/pdf")
        self.assertIn(
            "DEMO_Section18A_Receipt_", response.headers["content-disposition"]
        )
        self.assertIn(b"DEMO ONLY - NOT VALID FOR TAX PURPOSES", response.content)
        self.assertIn(b"No payment was processed or received.", response.content)

    def test_verified_tax_receipt_can_be_downloaded(self):
        token = "verified-receipt-access-token"
        with Session(self.engine) as session:
            donation = Donation(
                donor_name="Receipt Donor",
                donor_email="donor@example.org",
                request_tax_certificate=True,
                tax_id_number="1234567890",
                tax_address="1 Example Road",
                is_verified=True,
            )
            session.add(donation)
            session.flush()
            session.add(
                ReceiptAccess(
                    donation_id=donation.id,
                    token_hash=hashlib.sha256(token.encode("utf-8")).hexdigest(),
                    expires_at=datetime.now(timezone.utc) + timedelta(days=30),
                )
            )
            session.commit()

        csrf = self.csrf_token()
        receipt_response = self.client.post(
            "/donate/tax-certificate",
            data={"csrf_token": csrf, "receipt_token": token},
        )
        self.assertEqual(receipt_response.status_code, 200)
        self.assertEqual(receipt_response.headers["content-type"], "application/pdf")
        self.assertTrue(receipt_response.content.startswith(b"%PDF"))

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

    def test_news_image_can_be_updated_when_category_is_omitted(self):
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
                NewsArticle(
                    title="Story to update",
                    slug="story-to-update",
                    category="Youth",
                    summary="A short summary",
                    content="Full story content",
                )
            )
            session.commit()

        login, verification = self.login_staff(
            "admin@example.org", "CorrectHorseBatteryStaple1!"
        )
        self.assertEqual(login.status_code, 303, login.text)
        self.assertEqual(verification.status_code, 303, verification.text)

        response = self.client.post(
            "/admin/news/1/edit",
            data={
                "csrf_token": self.client.cookies.get("csrf_token"),
                "title": "Story to update",
                "summary": "A short summary",
                "content": "Full story content",
                "image_url": "/static/images/news/community-cook-off.png",
            },
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303, response.text)

        with Session(self.engine) as session:
            article = session.get(NewsArticle, 1)
        self.assertEqual(article.category, "Youth")
        self.assertEqual(
            article.image_url,
            "/static/images/news/community-cook-off.png",
        )

    def test_dashboard_recovers_from_invalid_volunteer_availability_json(self):
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
                Volunteer(
                    full_name="Test Volunteer",
                    phone="555-0100",
                    email="volunteer@example.org",
                    skills="Community support",
                    location="Cape Town",
                )
            )
            session.commit()

        with self.engine.begin() as connection:
            connection.execute(text("UPDATE volunteer SET available_days = ''"))

        _normalize_volunteer_available_days(self.engine)

        login, verification = self.login_staff(
            "admin@example.org", "CorrectHorseBatteryStaple1!"
        )
        self.assertEqual(login.status_code, 303, login.text)
        self.assertEqual(verification.status_code, 303, verification.text)
        dashboard = self.client.get("/admin/dashboard")
        self.assertEqual(dashboard.status_code, 200, dashboard.text[:1000])

        with Session(self.engine) as session:
            volunteer = session.exec(select(Volunteer)).one()
        self.assertEqual(volunteer.available_days, [])

    def test_dashboard_recovers_from_legacy_volunteer_status_values(self):
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
                Volunteer(
                    full_name="Test Volunteer",
                    phone="555-0100",
                    email="volunteer@example.org",
                    skills="Community support",
                    location="Cape Town",
                )
            )
            session.commit()

        with self.engine.begin() as connection:
            connection.execute(text("UPDATE volunteer SET status = 'Active'"))

        _normalize_volunteer_status(self.engine)

        login, verification = self.login_staff(
            "admin@example.org", "CorrectHorseBatteryStaple1!"
        )
        self.assertEqual(login.status_code, 303, login.text)
        self.assertEqual(verification.status_code, 303, verification.text)
        dashboard = self.client.get("/admin/dashboard")
        self.assertEqual(dashboard.status_code, 200, dashboard.text[:1000])

        with Session(self.engine) as session:
            volunteer = session.exec(select(Volunteer)).one()
        self.assertEqual(volunteer.status, VolunteerStatus.ACTIVE)

    def test_security_page_recovers_from_legacy_volunteer_user_role(self):
        with Session(self.engine) as session:
            session.add_all(
                [
                    User(
                        full_name="Administrator",
                        email="admin@example.org",
                        hashed_password=hash_password("CorrectHorseBatteryStaple1!"),
                        role=UserRole.ADMINISTRATOR,
                    ),
                    User(
                        full_name="Legacy Volunteer",
                        email="volunteer@example.org",
                        hashed_password=hash_password("CorrectHorseBatteryStaple1!"),
                        role=UserRole.USER,
                    ),
                ]
            )
            session.commit()

        with self.engine.begin() as connection:
            connection.execute(
                text("UPDATE [user] SET role = 'Volunteer' WHERE email = :email"),
                {"email": "volunteer@example.org"},
            )

        _normalize_user_roles(self.engine)

        with Session(self.engine) as session:
            legacy_user = session.exec(
                select(User).where(User.email == "volunteer@example.org")
            ).one()
        self.assertEqual(legacy_user.role, UserRole.USER)

        login, verification = self.login_staff(
            "admin@example.org", "CorrectHorseBatteryStaple1!"
        )
        self.assertEqual(login.status_code, 303, login.text)
        self.assertEqual(verification.status_code, 303, verification.text)
        security = self.client.get("/admin/security")
        self.assertEqual(security.status_code, 200, security.text[:1000])
        self.assertNotIn("volunteer@example.org", security.text)

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

        challenge, verification = self.login_staff(
            "admin@example.org", "CorrectHorseBatteryStaple1!"
        )
        self.assertEqual(challenge.status_code, 303, challenge.text)
        self.assertIn("max-age=300", challenge.headers["set-cookie"].lower())
        self.assertEqual(verification.status_code, 303, verification.text)
        self.assertIn("max-age=43200", verification.headers["set-cookie"].lower())
        dashboard = self.client.get("/admin/dashboard")
        self.assertEqual(dashboard.status_code, 200, dashboard.text[:1000])
        self.assertIn('id="tab-overview"', dashboard.text)
        self.assertNotIn('id="tab-donations"', dashboard.text)
        self.assertIn('id="notifications-panel"', dashboard.text)
        self.assertIn("Donation pledges to review", dashboard.text)
        self.assertRegex(
            dashboard.text,
            r'class="admin-header-icon-badge" id="notifications-badge"[^>]*>1</span>',
        )
        self.assertIn(
            'class="admin-user-initials" aria-hidden="true">A</span>', dashboard.text
        )
        self.assertIn(
            'class="admin-user-role-pill">Administration</span>', dashboard.text
        )
        donation_notification = re.search(
            r'data-notification-key="donations".*?data-notification-fingerprint="([0-9a-f]{64})"',
            dashboard.text,
            re.DOTALL,
        )
        self.assertIsNotNone(donation_notification)
        donations_dashboard = self.client.get("/admin/dashboard?tab=donations")
        self.assertEqual(
            donations_dashboard.status_code, 200, donations_dashboard.text[:1000]
        )
        self.assertIn('id="tab-donations"', donations_dashboard.text)
        self.assertNotIn('id="tab-overview"', donations_dashboard.text)
        self.assertIn("Donation pledges to review", donations_dashboard.text)
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
        self.assertIn('class="admin-workspace"', security.text)

    def test_shared_login_routes_staff_to_admin_dashboard(self):
        with Session(self.engine) as session:
            session.add(
                User(
                    full_name="Administrator",
                    email="shared-admin@example.org",
                    hashed_password=hash_password("CorrectHorseBatteryStaple1!"),
                    role=UserRole.ADMINISTRATOR,
                )
            )
            session.commit()

        response = self.client.get("/admin/login", follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/account/login")

        response = self.client.post(
            "/account/login",
            data={
                "csrf_token": self.csrf_token(),
                "email": "shared-admin@example.org",
                "password": "CorrectHorseBatteryStaple1!",
                "next_path": "/",
            },
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303, response.text)
        self.assertEqual(response.headers["location"], "/admin/mfa")
        self.assertTrue(self.client.cookies.get("staff_session"))
        self.assertFalse(self.client.cookies.get("user_session"))
        unauthorized = self.client.get("/admin/dashboard", follow_redirects=False)
        self.assertEqual(unauthorized.status_code, 401)
        self.assertEqual(unauthorized.json(), {"detail": "Staff sign-in required."})
        mfa_page = self.client.get("/admin/mfa")
        self.assertEqual(mfa_page.status_code, 200)
        with Session(self.engine) as session:
            auth_session = session.exec(select(AuthSession)).one()
            self.assertFalse(auth_session.mfa_verified)
            self.assertTrue(auth_session.mfa_setup_secret)
            setup_secret = auth_session.mfa_setup_secret
        grouped_secret = " ".join(
            setup_secret[index : index + 4]
            for index in range(0, len(setup_secret), 4)
        )
        self.assertIn(grouped_secret, mfa_page.text)
        self.assertIn("O is the letter, not zero", mfa_page.text)

        rejected_code = self.client.post(
            "/admin/mfa/verify",
            data={"code": "invalid"},
            headers={"X-CSRF-Token": self.client.cookies.get("csrf_token", "")},
            follow_redirects=False,
        )
        self.assertEqual(rejected_code.status_code, 401)
        verified = self.client.post(
            "/admin/mfa/verify",
            data={"code": totp_code(setup_secret)},
            headers={"X-CSRF-Token": self.client.cookies.get("csrf_token", "")},
            follow_redirects=False,
        )
        self.assertEqual(verified.status_code, 303)
        self.assertEqual(verified.headers["location"], "/admin/dashboard")
        self.assertEqual(self.client.get("/admin/dashboard").status_code, 200)

    def test_staff_login_rejects_invalid_passwords_and_public_accounts(self):
        with Session(self.engine) as session:
            session.add_all(
                [
                    User(
                        full_name="Administrator",
                        email="admin-login@example.org",
                        hashed_password=hash_password("CorrectHorseBatteryStaple1!"),
                        role=UserRole.ADMINISTRATOR,
                    ),
                    User(
                        full_name="Community Member",
                        email="public-login@example.org",
                        hashed_password=hash_password("CorrectHorseBatteryStaple1!"),
                        role=UserRole.USER,
                    ),
                ]
            )
            session.commit()

        csrf_token = self.csrf_token()
        for email, password in (
            ("admin-login@example.org", "IncorrectPassword1!"),
            ("public-login@example.org", "CorrectHorseBatteryStaple1!"),
            ("missing@example.org", "IncorrectPassword1!"),
        ):
            with self.subTest(email=email):
                response = self.client.post(
                    "/admin/login",
                    data={
                        "csrf_token": csrf_token,
                        "email": email,
                        "password": password,
                    },
                    follow_redirects=False,
                )
                self.assertEqual(response.status_code, 401)
                self.assertIn("Invalid email or password.", response.text)
                self.assertFalse(self.client.cookies.get(STAFF_COOKIE_NAME))
                self.assertFalse(self.client.cookies.get("user_session"))

        with Session(self.engine) as session:
            self.assertEqual(session.exec(select(AuthSession)).all(), [])

    def test_staff_authorization_rejects_expired_revoked_and_disallowed_roles(self):
        staff = User(
            full_name="Case Worker",
            email="caseworker@example.org",
            hashed_password=hash_password("CorrectHorseBatteryStaple1!"),
            role=UserRole.CASE_WORKER,
        )
        token = self.authenticate_staff(staff)
        dashboard = self.client.get("/admin/dashboard")
        self.assertEqual(dashboard.status_code, 200, dashboard.text[:500])
        self.assertEqual(self.client.get("/admin/staff").status_code, 403)

        self.client.cookies.set(STAFF_COOKIE_NAME, token)
        with Session(self.engine) as session:
            auth_session = session.exec(select(AuthSession)).one()
            session.delete(auth_session)
            session.commit()
        revoked = self.client.get("/admin/dashboard", follow_redirects=False)
        self.assertEqual(revoked.status_code, 401)
        self.assertEqual(revoked.json(), {"detail": "Staff sign-in required."})

        expired_staff = User(
            full_name="Expired Staff",
            email="expired-staff@example.org",
            hashed_password=hash_password("CorrectHorseBatteryStaple1!"),
            role=UserRole.ADMINISTRATOR,
        )
        self.authenticate_staff(
            expired_staff,
            expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),
        )
        expired = self.client.get("/admin/dashboard", follow_redirects=False)
        self.assertEqual(expired.status_code, 401)
        self.assertEqual(expired.json(), {"detail": "Staff sign-in required."})

    def test_enrolled_staff_must_verify_mfa_without_reenrolling(self):
        secret = "JBSWY3DPEHPK3PXP"
        with Session(self.engine) as session:
            session.add(
                User(
                    full_name="Enrolled Administrator",
                    email="enrolled-admin@example.org",
                    hashed_password=hash_password("CorrectHorseBatteryStaple1!"),
                    role=UserRole.ADMINISTRATOR,
                    mfa_secret=secret,
                )
            )
            session.commit()

        challenge, verification = self.login_staff(
            "enrolled-admin@example.org", "CorrectHorseBatteryStaple1!"
        )
        self.assertEqual(challenge.status_code, 303)
        self.assertEqual(challenge.headers["location"], "/admin/mfa")
        mfa_page = self.client.get("/admin/mfa")
        self.assertEqual(mfa_page.status_code, 200)
        self.assertNotIn(secret, mfa_page.text)
        self.assertEqual(verification.status_code, 303)
        self.assertEqual(self.client.get("/admin/dashboard").status_code, 200)

    def test_mfa_verification_attempts_are_rate_limited(self):
        with Session(self.engine) as session:
            session.add(
                User(
                    full_name="Administrator",
                    email="mfa-limited@example.org",
                    hashed_password=hash_password("CorrectHorseBatteryStaple1!"),
                    role=UserRole.ADMINISTRATOR,
                )
            )
            session.commit()

        csrf_token = self.csrf_token()
        challenge = self.client.post(
            "/admin/login",
            data={
                "csrf_token": csrf_token,
                "email": "mfa-limited@example.org",
                "password": "CorrectHorseBatteryStaple1!",
            },
            follow_redirects=False,
        )
        self.assertEqual(challenge.headers["location"], "/admin/mfa")
        for attempt in range(5):
            with self.subTest(attempt=attempt + 1):
                response = self.client.post(
                    "/admin/mfa/verify",
                    data={"code": "invalid"},
                    headers={"X-CSRF-Token": csrf_token},
                    follow_redirects=False,
                )
                self.assertEqual(response.status_code, 401)

        limited = self.client.post(
            "/admin/mfa/verify",
            data={"code": "invalid"},
            headers={"X-CSRF-Token": csrf_token},
            follow_redirects=False,
        )
        self.assertEqual(limited.status_code, 429)

    def test_donate_page_shows_admin_needs_and_full_story_on_detail_page(self):
        article = "Public details about the food parcel need are important. " * 8
        with Session(self.engine) as session:
            community_need = BeneficiaryNeed(
                is_community_need=True,
                contact_name="Private Contact",
                contact_phone="555-0100",
                full_address="Private Address",
                anonymised_title="Community food parcels",
                area="Kuils River",
                category="Food",
                article=article,
                status=NeedStatus.Open,
            )
            personal_request = BeneficiaryNeed(
                is_community_need=False,
                contact_name="Private Assistance Applicant",
                contact_phone="555-0199",
                full_address="Private Applicant Address",
                anonymised_title="Private beneficiary request",
                area="Kuils River",
                category="Food",
                status=NeedStatus.Open,
            )
            session.add(community_need)
            session.add(personal_request)
            session.commit()
            session.refresh(community_need)
            community_need_id = community_need.id
            personal_request_id = personal_request.id

        response = self.client.get("/donate")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn("Community needs", response.text)
        self.assertIn("Community food parcels", response.text)
        self.assertNotIn(article, response.text)
        excerpt_match = re.search(
            r'<p class="community-need-article[^"]*">(.*?)</p>',
            response.text,
            flags=re.DOTALL,
        )
        self.assertIsNotNone(excerpt_match)
        excerpt = excerpt_match.group(1)
        self.assertLessEqual(len(excerpt), 180)
        self.assertTrue(excerpt.endswith("…"))
        self.assertNotIn("Private beneficiary request", response.text)
        self.assertNotIn("Current campaigns", response.text)
        self.assertIn(f'href="/community-needs/{community_need_id}"', response.text)
        self.assertNotIn("Private Contact", response.text)
        self.assertNotIn("555-0100", response.text)
        self.assertNotIn("Private Address", response.text)
        self.assertNotIn("Private Assistance Applicant", response.text)
        self.assertNotIn("555-0199", response.text)
        self.assertNotIn("Private Applicant Address", response.text)

        detail = self.client.get(f"/community-needs/{community_need_id}")
        self.assertEqual(detail.status_code, 200, detail.text)
        self.assertIn(article, detail.text)
        self.assertIn(
            f'href="/donate?need_id={community_need_id}#donation-form"', detail.text
        )
        self.assertEqual(
            self.client.get(f"/community-needs/{personal_request_id}").status_code,
            404,
        )

    def test_public_community_needs_hide_rejected_and_archived_records(self):
        with Session(self.engine) as session:
            for title, need_status, archived in (
                ("Visible need", NeedStatus.PENDING, False),
                ("Fulfilled need", NeedStatus.FULFILLED, False),
                ("Rejected need", NeedStatus.REJECTED, False),
                ("Archived need", NeedStatus.Open, True),
                ("Private beneficiary case", NeedStatus.Open, False),
            ):
                session.add(
                    BeneficiaryNeed(
                        is_community_need=title != "Private beneficiary case",
                        contact_name="Private Contact",
                        contact_phone="555-0100",
                        full_address="Private Address",
                        anonymised_title=title,
                        area="Kuils River",
                        category="Food",
                        status=need_status,
                        archived_at=datetime.now(timezone.utc) if archived else None,
                    )
                )
            session.commit()

        response = self.client.get("/donate")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn("Visible need", response.text)
        self.assertIn("Fulfilled need", response.text)
        self.assertNotIn("Rejected need", response.text)
        self.assertNotIn("Archived need", response.text)
        self.assertNotIn("Private beneficiary case", response.text)

    def test_public_browse_pages_render(self):
        for path in ("/", "/about", "/donate", "/account/register"):
            response = self.client.get(path)
            self.assertEqual(
                response.status_code, 200, f"{path}: {response.text[:500]}"
            )
            self.assertIn('href="/static/css/tailwind.css"', response.text)
            self.assertNotIn("cdn.tailwindcss.com", response.text)
        stylesheet = self.client.get("/static/css/tailwind.css")
        self.assertEqual(stylesheet.status_code, 200)
        self.assertIn(".bg-brand-800", stylesheet.text)
        self.assertIn(".animate-pulse-heart", stylesheet.text)
        modern_stylesheet = self.client.get("/static/css/modern.css")
        self.assertEqual(modern_stylesheet.status_code, 200)
        self.assertIn("@media (max-width: 767px)", modern_stylesheet.text)
        self.assertIn("@media (min-width: 768px)", modern_stylesheet.text)
        self.assertIn(".mobile-menu-toggle", modern_stylesheet.text)
        normalized_stylesheet = modern_stylesheet.text.replace("\r\n", "\n")
        self.assertIn(".mobile-menu-toggle {\n    display: none;", normalized_stylesheet)
        admin_stylesheet = self.client.get("/static/css/admin-tailwind.css")
        self.assertEqual(admin_stylesheet.status_code, 200)
        self.assertIn(".bg-brand-900", admin_stylesheet.text)
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
        for image_name in (
            "community-cook-off.png",
            "financial-literacy.png",
            "mandela-day-and-youth-clean-up.png",
            "youth-employment.png",
        ):
            with self.subTest(image_name=image_name):
                image = self.client.get(f"/static/images/news/{image_name}")
                self.assertEqual(image.status_code, 200)
                self.assertEqual(image.headers["content-type"], "image/png")
                self.assertTrue(image.content)

    def test_public_campaign_query_compiles_for_sql_server(self):
        query = str(_public_campaigns_statement().compile(dialect=mssql.dialect()))
        self.assertIn("campaign.status IN", query)
        self.assertIn("campaign.archived_at IS NULL", query)

    def test_public_community_needs_query_compiles_for_sql_server(self):
        query = str(
            _public_community_needs_statement().compile(dialect=mssql.dialect())
        )
        self.assertIn("beneficiaryneed.is_community_need = 1", query)
        self.assertIn("beneficiaryneed.archived_at IS NULL", query)

    def test_verified_donation_query_uses_sql_server_bit_comparison(self):
        query = str(
            select(Donation)
            .where(Donation.is_verified == true())
            .compile(dialect=mssql.dialect())
        )
        self.assertIn("donation.is_verified = 1", query)
        self.assertNotIn("donation.is_verified IS 1", query)


if __name__ == "__main__":
    unittest.main()
