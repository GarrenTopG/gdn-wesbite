from decimal import Decimal

from sqlmodel import Session, select

from app.models.entities import BeneficiaryNeed, NeedUrgency, User, UserRole
from tests.support import DatabaseTestCase


class CommunityNeedAdminTests(DatabaseTestCase):
    def setUp(self):
        super().setUp()
        self.client.get("/account/login")
        self.csrf_token = self.client.cookies.get("csrf_token", "")
        admin = User(
            full_name="Needs Admin",
            email="needs-admin@example.org",
            hashed_password="not-used-in-this-test",
            role=UserRole.ADMINISTRATOR,
        )
        self.authenticate_staff(admin)

    def test_create_and_edit_community_need_content(self):
        data = {
            "anonymised_title": "Winter clothing support",
            "area": "Kuils River",
            "category": "Clothing",
            "urgency": "High",
            "target_amount": "2500.00",
            "deadline": "2026-12-01",
            "article": "Families need warm clothing.\n\nStaff are coordinating donations.",
            "image_url": "https://example.org/winter.jpg",
            "image_alt": "A pile of warm winter clothing",
        }
        response = self.client.post(
            "/admin/needs/add",
            data=data,
            headers={"X-CSRF-Token": self.csrf_token},
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 303, response.text)
        with Session(self.engine) as session:
            need = session.exec(
                select(BeneficiaryNeed).where(
                    BeneficiaryNeed.anonymised_title == "Winter clothing support"
                )
            ).one()
            need_id = need.id
            self.assertTrue(need.is_community_need)
            self.assertEqual(need.article, data["article"])
            self.assertEqual(need.image_url, data["image_url"])
            self.assertEqual(need.image_alt, data["image_alt"])

        dashboard = self.client.get("/admin/dashboard?tab=needs")
        self.assertEqual(dashboard.status_code, 200, dashboard.text)
        self.assertIn("Winter clothing support", dashboard.text)
        self.assertIn("Read article", dashboard.text)
        self.assertIn("A pile of warm winter clothing", dashboard.text)
        self.assertIn('id="editNeedModal"', dashboard.text)
        self.assertIn('id="editNeedForm"', dashboard.text)
        self.assertIn('data-title="Winter clothing support"', dashboard.text)

        public_page = self.client.get("/donate")
        self.assertEqual(public_page.status_code, 200, public_page.text)
        self.assertIn("Winter clothing support", public_page.text)
        self.assertIn(data["article"], public_page.text)
        self.assertIn(data["image_alt"], public_page.text)
        self.assertNotIn("Private address", public_page.text)
        self.assertNotIn("Private Contact", public_page.text)
        self.assertNotIn("needs-admin@example.org", public_page.text)

        edit_response = self.client.post(
            f"/admin/needs/{need_id}/edit",
            data={
                **data,
                "anonymised_title": "Updated winter clothing support",
                "urgency": "Critical",
                "article": "Updated article content.",
                "image_url": "",
                "image_alt": "",
            },
            headers={"X-CSRF-Token": self.csrf_token},
            follow_redirects=False,
        )
        self.assertEqual(edit_response.status_code, 303, edit_response.text)
        public_page = self.client.get("/donate")
        self.assertIn("Updated winter clothing support", public_page.text)
        self.assertIn("Updated article content.", public_page.text)
        self.assertNotIn("Winter clothing support", public_page.text)
        with Session(self.engine) as session:
            updated = session.get(BeneficiaryNeed, need_id)
            self.assertEqual(
                updated.anonymised_title, "Updated winter clothing support"
            )
            self.assertEqual(updated.urgency, NeedUrgency.CRITICAL)
            self.assertEqual(updated.target_amount, Decimal("2500.00"))
            self.assertEqual(updated.article, "Updated article content.")
            self.assertIsNone(updated.image_url)
            self.assertIsNone(updated.image_alt)

    def test_invalid_image_url_is_rejected(self):
        response = self.client.post(
            "/admin/needs/add",
            data={
                "anonymised_title": "Need with invalid image",
                "area": "Kuils River",
                "category": "Clothing",
                "urgency": "Medium",
                "target_amount": "0.00",
                "image_url": "javascript:alert(1)",
                "image_alt": "Invalid image",
            },
            headers={
                "X-CSRF-Token": self.csrf_token,
                "Accept": "text/html",
            },
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303, response.text)
        dashboard = self.client.get(response.headers["location"])
        self.assertEqual(dashboard.status_code, 200, dashboard.text)
        self.assertIn("Image URLs must use an HTTP or HTTPS URL.", dashboard.text)
        with Session(self.engine) as session:
            self.assertIsNone(
                session.exec(
                    select(BeneficiaryNeed).where(
                        BeneficiaryNeed.anonymised_title == "Need with invalid image"
                    )
                ).first()
            )

    def test_edit_validation_returns_to_dashboard_and_reopens_editor(self):
        create_response = self.client.post(
            "/admin/needs/add",
            data={
                "anonymised_title": "Need to edit",
                "area": "Kuils River",
                "category": "Clothing",
                "urgency": "Medium",
                "target_amount": "100.00",
                "image_url": "https://example.org/image.jpg",
                "image_alt": "A description",
            },
            headers={"X-CSRF-Token": self.csrf_token},
            follow_redirects=False,
        )
        self.assertEqual(create_response.status_code, 303, create_response.text)
        with Session(self.engine) as session:
            need_id = session.exec(
                select(BeneficiaryNeed).where(
                    BeneficiaryNeed.anonymised_title == "Need to edit"
                )
            ).one().id

        edit_data = {
            "anonymised_title": "Need to edit",
            "area": "Kuils River",
            "category": "Clothing",
            "urgency": "Medium",
            "target_amount": "100.00",
            "image_url": "https://example.org/image.jpg",
            "image_alt": "",
        }
        response = self.client.post(
            f"/admin/needs/{need_id}/edit",
            data=edit_data,
            headers={
                "X-CSRF-Token": self.csrf_token,
                "Accept": "text/html",
            },
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303, response.text)
        self.assertIn("tab=needs", response.headers["location"])
        self.assertIn("form_modal=editNeed", response.headers["location"])
        self.assertIn(f"edit_need_id={need_id}", response.headers["location"])
        dashboard = self.client.get(response.headers["location"])
        self.assertEqual(dashboard.status_code, 200, dashboard.text)
        self.assertIn("Provide descriptive alt text for the image.", dashboard.text)
        self.assertIn(f'id="edit-need-{need_id}"', dashboard.text)

        missing_field_response = self.client.post(
            f"/admin/needs/{need_id}/edit",
            data={key: value for key, value in edit_data.items() if key != "category"},
            headers={
                "X-CSRF-Token": self.csrf_token,
                "Accept": "text/html",
            },
            follow_redirects=False,
        )
        self.assertEqual(missing_field_response.status_code, 303)
        missing_field_dashboard = self.client.get(
            missing_field_response.headers["location"]
        )
        self.assertEqual(missing_field_dashboard.status_code, 200)
        self.assertIn(
            "Some required fields are missing or invalid.",
            missing_field_dashboard.text,
        )
        json_validation_response = self.client.post(
            f"/admin/needs/{need_id}/edit",
            data={key: value for key, value in edit_data.items() if key != "category"},
            headers={
                "X-CSRF-Token": self.csrf_token,
                "Accept": "application/json",
            },
            follow_redirects=False,
        )
        self.assertEqual(json_validation_response.status_code, 422)
        self.assertIn("detail", json_validation_response.json())
        with Session(self.engine) as session:
            unchanged = session.get(BeneficiaryNeed, need_id)
            self.assertEqual(unchanged.anonymised_title, "Need to edit")
