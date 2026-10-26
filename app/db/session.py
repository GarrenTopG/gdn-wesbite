import os

from dotenv import load_dotenv
from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine, URL
from sqlmodel import Session, create_engine

load_dotenv()


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


DATABASE_SCHEMA_REVISION = "a4d85d1c6f20"


def validate_database_ready(database_engine: Engine | None = None) -> None:
    """Validate connectivity and require an explicitly migrated database."""
    database_engine = database_engine or engine
    with database_engine.connect() as connection:
        connection.execute(text("SELECT 1"))
        if not inspect(connection).has_table("alembic_version"):
            raise RuntimeError(
                "Database migrations are required. Back up the database, then run "
                "'python -m alembic upgrade head' before starting the application."
            )
        revision = connection.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one_or_none()
    if revision != DATABASE_SCHEMA_REVISION:
        raise RuntimeError(
            "Database schema is not at the supported migration revision. "
            "Run 'python -m alembic upgrade head' before starting the application."
        )


# Dependency injector for database sessions in FastAPI endpoints
def get_session():
    """Dependency injector for database sessions in FastAPI endpoints."""
    with Session(engine) as session:
        try:
            yield session
        except Exception:
            session.rollback()
            raise
