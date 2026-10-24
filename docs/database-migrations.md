# Database access and migrations

## Database access and transactions

The application uses synchronous SQLModel `Session` instances and synchronous FastAPI
route handlers whenever a handler accesses the database. FastAPI runs those handlers in
its worker thread pool rather than blocking the event loop. For multipart forms, the
asynchronous form parser dependency reads the request body before the synchronous handler
runs.

Routes own the transaction for a request: they flush when they need generated identifiers
and commit once the complete operation is ready. Persistence helpers may add related
records, but do not commit. The donation submission service adds the donation and its
history row in the same transaction; a failure before the route commits rolls both back.
The rate-limit dependency commits its rate-limit hit before the handler begins because it
is a separate operation with an independent lifecycle.

`get_session` rolls back on unhandled exceptions and closes the session after the request.
Do not share a `Session` between concurrent tasks, commit from a helper midway through a
larger operation, or perform synchronous ORM work in an `async def` route.

## Creating and upgrading a database

Install runtime dependencies as usual, then install the migration dependency:

```powershell
python -m pip install -r requirements-migrations.txt
```

`DATABASE_BACKEND`, `SQLITE_FILE_NAME`, and the `MSSQL_*` settings are shared by the
application and Alembic. For a new SQLite database, the default target is `aurorah.db`.
Initialize it before starting the application:

```powershell
python -m alembic upgrade head
```

The initial revision creates the current schema for an empty database. The next revision
also upgrades supported pre-migration SQLite and SQL Server schemas, applies required
legacy data normalization, backfills allocation and publication data, and seeds the
supplied community stories. The migration version is stored in `alembic_version`.
Application startup only checks connectivity and that the database is at the supported
revision; it never runs schema changes automatically.

## Production migration procedure

1. Schedule a maintenance window and stop the application or otherwise prevent writes.
2. Take a consistent, restorable backup before each migration. For SQLite, stop all
   writers and use SQLite's backup facility or copy the database only after it is closed.
   For SQL Server, take a full database backup and verify that the backup is restorable.
3. Install the application and `requirements-migrations.txt` in the migration environment.
   Set the same database environment variables used by the application.
4. Review the pending migration revisions, then run `python -m alembic upgrade head`.
5. Verify the reported Alembic revision, start the application, and check its readiness
   and application logs before reopening traffic.
6. If a migration fails or the upgraded application cannot be safely restored, keep
   traffic stopped and restore the verified backup. The legacy data migration is
   intentionally irreversible; do not use `alembic downgrade` as a production rollback.

For future schema work, add a new revision, review and test its generated operations
against both SQLite and SQL Server, and include any required data backfill in that
revision. Do not edit an already-applied revision or use `metadata.create_all()` as a
production upgrade mechanism.

The automated migration suite applies fresh and legacy upgrades on isolated SQLite
databases and compiles schema DDL and selected critical queries with the SQL Server
dialect. Compilation does not exercise a SQL Server driver, database constraints,
transaction behavior, or migration execution. Before deploying a migration to SQL
Server, run the upgrade and critical query suite against a dedicated disposable SQL
Server database with the same server and driver versions as production.
