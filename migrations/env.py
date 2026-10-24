import os

from alembic import context
from sqlalchemy import create_engine, pool
from sqlmodel import SQLModel

from app.db.session import engine as application_engine
from app.models import entities  # noqa: F401

config = context.config
target_metadata = SQLModel.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=str(application_engine.url),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    supplied_connection = config.attributes.get("connection")
    if supplied_connection is not None:
        context.configure(
            connection=supplied_connection,
            target_metadata=target_metadata,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()
        return

    migration_url = os.getenv("MIGRATION_DATABASE_URL")
    connectable = (
        create_engine(migration_url, poolclass=pool.NullPool)
        if migration_url
        else application_engine
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()
    if migration_url:
        connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
