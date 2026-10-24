from pathlib import Path
from importlib import import_module

from alembic import command
from alembic.config import Config
from sqlalchemy.engine import Engine

legacy_schema_revision = import_module(
    "migrations.versions.3e1c449879e2_legacy_schema_and_data"
)


def upgrade_test_database(engine: Engine) -> None:
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "head")


def normalize_user_roles(engine: Engine) -> None:
    with engine.begin() as connection:
        legacy_schema_revision._normalize_user_roles(connection)


def normalize_volunteer_available_days(engine: Engine) -> None:
    with engine.begin() as connection:
        legacy_schema_revision._normalize_volunteer_available_days(connection)


def normalize_volunteer_status(engine: Engine) -> None:
    with engine.begin() as connection:
        legacy_schema_revision._normalize_volunteer_status(connection)
