import json
import logging
import os

from dotenv import load_dotenv
from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine, URL
from sqlmodel import SQLModel, Session, create_engine

from app.news_content import seed_community_stories

load_dotenv()

logger = logging.getLogger(__name__)

LEGACY_SEEDED_NEWS_SLUGS = (
    "shifting-mindsets-financial-skills-training-program-with-avo-vision",
)


def _normalize_volunteer_available_days(database_engine: Engine) -> None:
    with database_engine.begin() as connection:
        rows = connection.execute(
            text(
                "SELECT id, available_days FROM volunteer "
                "WHERE available_days IS NOT NULL"
            )
        )
        invalid_ids = []
        for volunteer_id, available_days in rows:
            try:
                parsed_days = json.loads(available_days)
            except (json.JSONDecodeError, TypeError):
                invalid_ids.append(volunteer_id)
                continue
            if not isinstance(parsed_days, list) or any(
                not isinstance(day, str) for day in parsed_days
            ):
                invalid_ids.append(volunteer_id)

        if invalid_ids:
            connection.execute(
                text(
                    "UPDATE volunteer SET available_days = '[]' "
                    "WHERE id = :volunteer_id"
                ),
                [{"volunteer_id": volunteer_id} for volunteer_id in invalid_ids],
            )
            logger.warning(
                "Reset invalid volunteer.available_days values for %d records",
                len(invalid_ids),
            )


def _normalize_volunteer_status(database_engine: Engine) -> None:
    from app.models.entities import VolunteerStatus

    status_lookup = {
        candidate.casefold(): member.name
        for member in VolunteerStatus
        for candidate in (member.name, member.value)
    }
    with database_engine.begin() as connection:
        rows = connection.execute(text("SELECT id, status FROM volunteer"))
        updates = []
        for volunteer_id, current_status in rows:
            normalized_status = status_lookup.get(
                current_status.strip().casefold()
                if isinstance(current_status, str)
                else ""
            )
            if normalized_status is None:
                normalized_status = VolunteerStatus.ACTIVE.name
            if current_status != normalized_status:
                updates.append(
                    {
                        "volunteer_id": volunteer_id,
                        "status": normalized_status,
                    }
                )

        if updates:
            connection.execute(
                text("UPDATE volunteer SET status = :status WHERE id = :volunteer_id"),
                updates,
            )
            logger.warning(
                "Normalized invalid volunteer.status values for %d records",
                len(updates),
            )


def _normalize_user_roles(database_engine: Engine) -> None:
    from app.models.entities import UserRole

    role_lookup = {
        candidate.casefold(): role.name
        for role in UserRole
        for candidate in (role.name, role.value)
    }
    role_lookup["admin"] = UserRole.ADMINISTRATOR.name
    role_lookup["volunteer"] = UserRole.USER.name

    with database_engine.begin() as connection:
        rows = connection.execute(text("SELECT id, role FROM [user]"))
        updates = []
        for user_id, current_role in rows:
            normalized_role = role_lookup.get(
                current_role.strip().casefold()
                if isinstance(current_role, str)
                else ""
            )
            if normalized_role is None:
                normalized_role = UserRole.USER.name
            if current_role != normalized_role:
                updates.append({"user_id": user_id, "role": normalized_role})

        if updates:
            connection.execute(
                text("UPDATE [user] SET role = :role WHERE id = :user_id"),
                updates,
            )
            logger.warning(
                "Normalized legacy or invalid user.role values for %d records",
                len(updates),
            )


def _create_engine() -> Engine:
    backend = os.getenv("DATABASE_BACKEND", "sqlite").strip().lower()
    if backend == "sqlite":
        sqlite_file_name = os.getenv("SQLITE_FILE_NAME", "aurorah.db")
        return create_engine(
            f"sqlite:///{sqlite_file_name}",
            connect_args={"check_same_thread": False},
        )
    if backend != "sqlserver":
        raise ValueError("DATABASE_BACKEND must be either 'sqlite' or 'sqlserver'.")

    required_settings = {
        "MSSQL_SERVER": os.getenv("MSSQL_SERVER"),
        "MSSQL_DATABASE": os.getenv("MSSQL_DATABASE"),
        "MSSQL_USERNAME": os.getenv("MSSQL_USERNAME"),
        "MSSQL_PASSWORD": os.getenv("MSSQL_PASSWORD"),
    }
    missing_settings = [key for key, value in required_settings.items() if not value]
    if missing_settings:
        raise RuntimeError(
            "SQL Server configuration is missing: " + ", ".join(missing_settings)
        )

    connection_url = URL.create(
        "mssql+pyodbc",
        username=required_settings["MSSQL_USERNAME"],
        password=required_settings["MSSQL_PASSWORD"],
        host=required_settings["MSSQL_SERVER"],
        database=required_settings["MSSQL_DATABASE"],
        query={
            "driver": os.getenv("MSSQL_DRIVER", "ODBC Driver 18 for SQL Server"),
            "Encrypt": "yes",
            "TrustServerCertificate": "no",
        },
    )
    return create_engine(connection_url, pool_pre_ping=True, pool_recycle=1800)


engine = _create_engine()


def _create_sqlserver_audit_triggers():
    trigger_statements = (
        "CREATE OR ALTER TRIGGER auditlog_no_update ON auditlog "
        "INSTEAD OF UPDATE AS BEGIN "
        ";THROW 50000, 'audit log is immutable', 1; END",
        "CREATE OR ALTER TRIGGER auditlog_no_delete ON auditlog "
        "INSTEAD OF DELETE AS BEGIN "
        ";THROW 50000, 'audit log is immutable', 1; END",
        "CREATE OR ALTER TRIGGER recordhistory_no_update ON recordhistory "
        "INSTEAD OF UPDATE AS BEGIN "
        ";THROW 50000, 'record history is immutable', 1; END",
        "CREATE OR ALTER TRIGGER recordhistory_no_delete ON recordhistory "
        "INSTEAD OF DELETE AS BEGIN "
        ";THROW 50000, 'record history is immutable', 1; END",
    )
    with engine.begin() as connection:
        for statement in trigger_statements:
            connection.execute(text(statement))

# Create the database and tables if they don't exist
def create_db_and_tables():
    """Initializes and creates all database tables."""
    import app.models.entities  # noqa: F401 - ensure all tables are registered with SQLModel.metadata
    if engine.dialect.name == "mssql":
        auto_create_schema = os.getenv(
            "DATABASE_AUTO_CREATE_SCHEMA", "false"
        ).strip().lower()
        if auto_create_schema not in {"true", "false"}:
            raise ValueError("DATABASE_AUTO_CREATE_SCHEMA must be 'true' or 'false'.")
        if auto_create_schema == "true":
            SQLModel.metadata.create_all(engine)
            _create_sqlserver_audit_triggers()
        else:
            existing_tables = set(inspect(engine).get_table_names())
            missing_tables = sorted(set(SQLModel.metadata.tables) - existing_tables)
            if missing_tables:
                raise RuntimeError(
                    "SQL Server schema is not initialized. Run the documented "
                    "one-time schema setup before starting the website."
                )
        news_columns = {
            column["name"] for column in inspect(engine).get_columns("newsarticle")
        }
        if "published_date" not in news_columns:
            with engine.begin() as connection:
                connection.execute(
                    text("ALTER TABLE newsarticle ADD published_date DATE NULL")
                )
                connection.execute(
                    text(
                        "UPDATE newsarticle SET published_date = "
                        "CAST(created_at AS DATE) WHERE published_date IS NULL"
                    )
                )
        user_columns = {
            column["name"] for column in inspect(engine).get_columns("user")
        }
        need_columns = {
            column["name"]
            for column in inspect(engine).get_columns("beneficiaryneed")
        }
        with engine.begin() as connection:
            if "phone_number" not in user_columns:
                connection.execute(
                    text("ALTER TABLE [user] ADD phone_number NVARCHAR(50) NULL")
                )
            if "preferences" not in user_columns:
                connection.execute(
                    text("ALTER TABLE [user] ADD preferences NVARCHAR(MAX) NULL")
                )
            if "user_id" not in need_columns:
                connection.execute(
                    text(
                        "ALTER TABLE beneficiaryneed "
                        "ADD user_id INT NULL"
                    )
                )
        with Session(engine) as session:
            seed_community_stories(session)
            session.commit()
        _normalize_user_roles(engine)
        _normalize_volunteer_available_days(engine)
        _normalize_volunteer_status(engine)
        return

    SQLModel.metadata.create_all(engine)
    inspector = inspect(engine)
    columns = {column["name"] for column in inspector.get_columns("beneficiaryneed")}
    volunteer_columns = {
        column["name"] for column in inspector.get_columns("volunteer")
    }
    match_columns = {
        column["name"] for column in inspector.get_columns("volunteermatch")
    }
    donation_columns = {
        column["name"] for column in inspector.get_columns("donation")
    }
    news_columns = {
        column["name"] for column in inspector.get_columns("newsarticle")
    }
    with engine.begin() as connection:
        if "published_date" not in news_columns:
            connection.execute(
                text("ALTER TABLE newsarticle ADD COLUMN published_date DATE")
            )
            connection.execute(
                text(
                    "UPDATE newsarticle SET published_date = date(created_at) "
                    "WHERE published_date IS NULL"
                )
            )
        if "request_details" not in columns:
            connection.execute(
                text("ALTER TABLE beneficiaryneed ADD COLUMN request_details TEXT")
            )
        if "closed_at" not in columns:
            connection.execute(text("ALTER TABLE beneficiaryneed ADD COLUMN closed_at DATETIME"))
        if "is_community_need" not in columns:
            connection.execute(
                text(
                    "ALTER TABLE beneficiaryneed "
                    "ADD COLUMN is_community_need BOOLEAN NOT NULL DEFAULT 0"
                )
            )
        for name, definition in (
            ("assigned_staff_id", "INTEGER"),
            ("internal_notes", "TEXT"),
            ("follow_up_at", "DATETIME"),
            ("deadline", "DATETIME"),
            ("archived_at", "DATETIME"),
        ):
            if name not in columns:
                connection.execute(
                    text(f"ALTER TABLE beneficiaryneed ADD COLUMN {name} {definition}")
                )
        if "onboarding_status" not in volunteer_columns:
            connection.execute(
                text(
                    "ALTER TABLE volunteer ADD COLUMN onboarding_status "
                    "TEXT NOT NULL DEFAULT 'Pending'"
                )
            )
        if "next_assignment_at" not in volunteer_columns:
            connection.execute(
                text("ALTER TABLE volunteer ADD COLUMN next_assignment_at DATETIME")
            )
        if "archived_at" not in volunteer_columns:
            connection.execute(text("ALTER TABLE volunteer ADD COLUMN archived_at DATETIME"))
        if "assigned_for" not in match_columns:
            connection.execute(
                text("ALTER TABLE volunteermatch ADD COLUMN assigned_for DATETIME")
            )
        if "status" not in donation_columns:
            connection.execute(
                text(
                    "ALTER TABLE donation ADD COLUMN status "
                    "TEXT NOT NULL DEFAULT 'Submitted'"
                )
            )
            connection.execute(
                text(
                    "UPDATE donation SET status = CASE "
                    "WHEN is_verified = 1 AND amount > 0 "
                    "AND allocated_amount >= amount THEN 'Allocated' "
                    "WHEN is_verified = 1 THEN 'Received/Verified' "
                    "ELSE 'Payment Pending' END"
                )
            )
        if "archived_at" not in donation_columns:
            connection.execute(text("ALTER TABLE donation ADD COLUMN archived_at DATETIME"))
        if "pending_receipt_token_hash" not in donation_columns:
            connection.execute(
                text("ALTER TABLE donation ADD COLUMN pending_receipt_token_hash TEXT")
            )
        connection.execute(
            text(
                "INSERT INTO donationallocation (donation_id, need_id, amount, created_at) "
                "SELECT d.id, d.need_id, d.allocated_amount, CURRENT_TIMESTAMP "
                "FROM donation d "
                "WHERE d.need_id IS NOT NULL AND d.allocated_amount > 0 "
                "AND NOT EXISTS ("
                "SELECT 1 FROM donationallocation a "
                "WHERE a.donation_id = d.id AND a.need_id = d.need_id)"
            )
        )
        if "status" not in news_columns:
            connection.execute(
                text(
                    "ALTER TABLE newsarticle ADD COLUMN status "
                    "TEXT NOT NULL DEFAULT 'Published'"
                )
            )
        if "archived_at" not in news_columns:
            connection.execute(text("ALTER TABLE newsarticle ADD COLUMN archived_at DATETIME"))
        user_columns = {
            column["name"] for column in inspect(engine).get_columns("user")
        }
        if "mfa_secret" not in user_columns:
            connection.execute(text("ALTER TABLE user ADD COLUMN mfa_secret TEXT"))
        if "mfa_last_counter" not in user_columns:
            connection.execute(
                text("ALTER TABLE user ADD COLUMN mfa_last_counter INTEGER")
            )
        if "phone_number" not in user_columns:
            connection.execute(
                text("ALTER TABLE user ADD COLUMN phone_number VARCHAR(50)")
            )
        if "preferences" not in user_columns:
            connection.execute(
                text("ALTER TABLE user ADD COLUMN preferences JSON")
            )
        if "user_id" not in columns:
            connection.execute(
                text("ALTER TABLE beneficiaryneed ADD COLUMN user_id INTEGER")
            )
        auth_session_columns = {
            column["name"] for column in inspect(engine).get_columns("authsession")
        }
        if "mfa_verified" not in auth_session_columns:
            connection.execute(
                text(
                    "ALTER TABLE authsession ADD COLUMN "
                    "mfa_verified BOOLEAN NOT NULL DEFAULT 0"
                )
            )
        if "mfa_setup_secret" not in auth_session_columns:
            connection.execute(
                text("ALTER TABLE authsession ADD COLUMN mfa_setup_secret TEXT")
            )
        for table, column in (
            ("beneficiaryneed", "assigned_staff_id"),
            ("beneficiaryneed", "follow_up_at"),
            ("beneficiaryneed", "deadline"),
            ("beneficiaryneed", "archived_at"),
            ("volunteer", "onboarding_status"),
            ("volunteer", "next_assignment_at"),
            ("volunteer", "archived_at"),
            ("volunteermatch", "assigned_for"),
            ("donation", "status"),
            ("donation", "archived_at"),
            ("donation", "pending_receipt_token_hash"),
            ("newsarticle", "status"),
            ("newsarticle", "archived_at"),
        ):
            connection.execute(
                text(
                    f"CREATE INDEX IF NOT EXISTS ix_{table}_{column} "
                    f"ON {table} ({column})"
                )
            )
        connection.execute(
            text(
                "CREATE TRIGGER IF NOT EXISTS auditlog_no_update "
                "BEFORE UPDATE ON auditlog BEGIN "
                "SELECT RAISE(ABORT, 'audit log is immutable'); END"
            )
        )
        connection.execute(
            text(
                "CREATE TRIGGER IF NOT EXISTS auditlog_no_delete "
                "BEFORE DELETE ON auditlog BEGIN "
                "SELECT RAISE(ABORT, 'audit log is immutable'); END"
            )
        )
        connection.execute(
            text(
                "CREATE TRIGGER IF NOT EXISTS recordhistory_no_update "
                "BEFORE UPDATE ON recordhistory BEGIN "
                "SELECT RAISE(ABORT, 'record history is immutable'); END"
            )
        )
        connection.execute(
            text(
                "CREATE TRIGGER IF NOT EXISTS recordhistory_no_delete "
                "BEFORE DELETE ON recordhistory BEGIN "
                "SELECT RAISE(ABORT, 'record history is immutable'); END"
            )
        )
        for slug in LEGACY_SEEDED_NEWS_SLUGS:
            connection.execute(
                text("DELETE FROM newsarticle WHERE slug = :slug"),
                {"slug": slug},
            )
        connection.execute(
            text(
                "UPDATE beneficiaryneed "
                "SET is_community_need = 1, contact_name = '', contact_phone = '', "
                "full_address = '' "
                "WHERE contact_name = 'Admin Internal' "
                "OR full_address = 'Admin Direct Entry'"
            )
        )

    _normalize_user_roles(engine)
    _normalize_volunteer_available_days(engine)
    _normalize_volunteer_status(engine)
    with Session(engine) as session:
        seed_community_stories(session)
        session.commit()

# Dependency injector for database sessions in FastAPI endpoints
def get_session():
    """Dependency injector for database sessions in FastAPI endpoints."""
    with Session(engine) as session:
        yield session