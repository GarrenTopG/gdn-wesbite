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
    columns = {column["name"] for column in inspect(engine).get_columns("beneficiaryneed")}
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