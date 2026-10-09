from sqlalchemy import inspect, text
from sqlmodel import SQLModel, Session, create_engine

LEGACY_SEEDED_NEWS_SLUGS = (
    "another-big-win-for-our-youth-financial-literacy-employment-milestones",
    "a-win-worth-celebrating-3-more-youth-secure-full-time-contracts",
    "shifting-mindsets-financial-skills-training-program-with-avo-vision",
    "serving-hope-and-warmth-community-cook-off-supports-over-400-residents",
)

# SQLite database file path
sqlite_file_name = "aurorah.db"
sqlite_url = f"sqlite:///{sqlite_file_name}"

# Create the SQLAlchemy engine for SQLite with the specified URL and connection arguments
engine = create_engine(sqlite_url, connect_args={"check_same_thread": False})

# Create the database and tables if they don't exist
def create_db_and_tables():
    """Initializes and creates all database tables."""
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
                "UPDATE user SET role = 'ADMINISTRATOR' "
                "WHERE role IN ('ADMIN', 'admin')"
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
        connection.execute(
            text(
                "DELETE FROM newsarticle WHERE slug IN "
                "(:slug0, :slug1, :slug2, :slug3)"
            ),
            {
                f"slug{index}": slug
                for index, slug in enumerate(LEGACY_SEEDED_NEWS_SLUGS)
            },
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

# Dependency injector for database sessions in FastAPI endpoints
def get_session():
    """Dependency injector for database sessions in FastAPI endpoints."""
    with Session(engine) as session:
        yield session