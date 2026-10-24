from datetime import datetime
from decimal import Decimal
import unittest

from sqlalchemy import inspect, text
from sqlalchemy.dialects import mssql
from sqlalchemy.schema import CreateIndex, CreateTable
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.db.session import DATABASE_SCHEMA_REVISION, validate_database_ready
from app.models.entities import (
    BeneficiaryNeed,
    Donation,
    DonationAllocation,
    NewsArticle,
    User,
    UserRole,
    Volunteer,
    VolunteerStatus,
)
from tests.migration_support import upgrade_test_database


class DatabaseMigrationTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        self.addCleanup(self.engine.dispose)

    def test_unversioned_database_fails_readiness_validation(self):
        with self.assertRaisesRegex(RuntimeError, "migrations are required"):
            validate_database_ready(self.engine)

    def test_schema_ddl_compiles_for_sql_server(self):
        dialect = mssql.dialect()
        for table in SQLModel.metadata.sorted_tables:
            str(CreateTable(table).compile(dialect=dialect))
            for index in table.indexes:
                str(CreateIndex(index).compile(dialect=dialect))

    def test_fresh_database_migrates_to_head(self):
        upgrade_test_database(self.engine)

        validate_database_ready(self.engine)
        with self.engine.connect() as connection:
            revision = connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one()
            self.assertEqual(revision, DATABASE_SCHEMA_REVISION)
        tables = set(inspect(self.engine).get_table_names())
        self.assertTrue(set(SQLModel.metadata.tables).issubset(tables))
        with Session(self.engine) as session:
            self.assertEqual(len(session.exec(select(NewsArticle)).all()), 5)

    def test_existing_schema_is_upgraded_and_legacy_data_preserved(self):
        SQLModel.metadata.create_all(self.engine)
        with Session(self.engine) as session:
            need = BeneficiaryNeed(
                contact_name="Admin Internal",
                contact_phone="",
                full_address="Admin Direct Entry",
                anonymised_title="Internal need",
                area="",
                category="Food",
            )
            session.add(need)
            session.flush()
            session.add(
                Donation(
                    donor_name="Legacy donor",
                    need_id=need.id,
                    amount=Decimal("100.00"),
                    allocated_amount=Decimal("100.00"),
                    is_verified=True,
                )
            )
            session.add(
                NewsArticle(
                    title="Legacy article",
                    slug="legacy-article",
                    category="Community",
                    summary="Legacy summary",
                    content="Legacy content",
                    status="Published",
                    created_at=datetime(2024, 1, 2),
                )
            )
            session.add(
                User(
                    full_name="Legacy administrator",
                    email="legacy-admin@example.org",
                    hashed_password="not-used-in-this-test",
                )
            )
            session.add(
                Volunteer(
                    full_name="Legacy volunteer",
                    phone="",
                    email="legacy-volunteer@example.org",
                    skills="",
                    location="",
                    available_days=["Monday"],
                    status=VolunteerStatus.ACTIVE,
                )
            )
            session.commit()

        with self.engine.begin() as connection:
            connection.execute(
                text("UPDATE [user] SET role = 'admin' WHERE email = :email"),
                {"email": "legacy-admin@example.org"},
            )
            connection.execute(
                text(
                    "UPDATE volunteer SET status = 'invalid', available_days = "
                    "'not-json' WHERE email = :email"
                ),
                {"email": "legacy-volunteer@example.org"},
            )

        columns_to_remove = {
            "beneficiaryneed": {"request_details", "is_community_need"},
            "donation": {"status"},
            "newsarticle": {"published_date", "status"},
            "volunteer": {"onboarding_status"},
        }
        with self.engine.begin() as connection:
            inspector = inspect(connection)
            for table, removed_columns in columns_to_remove.items():
                for index in inspector.get_indexes(table):
                    if removed_columns.intersection(index["column_names"]):
                        connection.exec_driver_sql(f'DROP INDEX "{index["name"]}"')
                for column in removed_columns:
                    connection.exec_driver_sql(
                        f'ALTER TABLE "{table}" DROP COLUMN "{column}"'
                    )

        upgrade_test_database(self.engine)

        with Session(self.engine) as session:
            need = session.exec(
                select(BeneficiaryNeed).where(BeneficiaryNeed.contact_name == "")
            ).one()
            donation = session.exec(select(Donation)).one()
            article = session.exec(
                select(NewsArticle).where(NewsArticle.slug == "legacy-article")
            ).one()
            allocations = session.exec(select(DonationAllocation)).all()
            administrator = session.exec(
                select(User).where(User.email == "legacy-admin@example.org")
            ).one()
            volunteer = session.exec(
                select(Volunteer).where(
                    Volunteer.email == "legacy-volunteer@example.org"
                )
            ).one()

        self.assertTrue(need.is_community_need)
        self.assertEqual(need.full_address, "")
        self.assertEqual(donation.status, "Allocated")
        self.assertEqual(len(allocations), 1)
        self.assertEqual(article.published_date.isoformat(), "2024-01-02")
        self.assertEqual(administrator.role, UserRole.ADMINISTRATOR)
        self.assertEqual(volunteer.status, VolunteerStatus.ACTIVE)
        self.assertEqual(volunteer.available_days, [])
