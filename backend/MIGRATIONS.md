# Rebly AI database migrations

Alembic is the only schema owner in staging and production. API startup must
not create tables or run data backfills there.

## Deployment policy

Run from the `backend` directory with the same `DATABASE_URL` that the API will
use:

```powershell
alembic upgrade head
alembic current
alembic check
```

The expected current revision is `0005_schema_contract_guard (head)`. Start API
and worker replicas only after the migration command succeeds. `/readyz`
returns HTTP 503 while the database is unavailable or its Alembic revision is
not exactly at head.

Production configuration must include:

```dotenv
APP_ENV=production
DATABASE_AUTO_CREATE_SCHEMA=false
DATABASE_STARTUP_BACKFILL=false
YOUTUBE_SNAPSHOT_WORKER_RUN_IN_API=false
```

Use `python -m app.youtube_growth.worker_main` for the dedicated snapshot
worker. Never run that loop inside every API replica.

## Fresh database

Create an empty database and run `alembic upgrade head`. The complete legacy,
core-domain, YouTube Growth, and scheduled-delivery schema is created from
revisions 0001-0005. Revision 0005 validates every ORM table/column and the
critical Connected Apps uniqueness constraints, so an incomplete adopted
legacy schema fails before application traffic starts.
Do not call `Base.metadata.create_all()` in a deployment job.

## Existing database without `alembic_version`

Older installations may already contain tables created by SQLAlchemy ORM.
Adopt one safely as follows:

1. Stop writes or enter a maintenance window.
2. Take a database-native backup and verify that it can be restored.
3. Restore that backup into a staging database.
4. Run `alembic current`; no revision output confirms it is unversioned.
5. Run `alembic upgrade head` against the staging copy.
6. Run `alembic current`, `alembic check`, application tests, and `/readyz`.
7. Only after the staging copy passes, repeat the upgrade on production.

The baseline revisions preserve compatible pre-existing tables and data. The
YouTube revision accepts an existing complete ORM-created table set, but aborts
on a partial or incompatible set so an operator can reconcile it without data
loss.

Do **not** run `alembic stamp head` merely to silence readiness. Stamping marks
a schema as migrated without applying or validating it. Use it only after a
DBA has compared every table, column, constraint, and index to the migration
metadata and recorded that review.

## Rollback and recovery

Migration downgrades can remove application data. For a failed production
release, stop the new application version and restore the verified backup, or
ship a reviewed forward-fix migration. Test the chosen recovery procedure on a
production-like copy before the maintenance window.

## Local development compatibility

Development and test environments default to ORM schema creation and startup
backfill when the two `DATABASE_*` flags are omitted. `.env.example` sets them
to `true` explicitly for clarity. Local developers can instead use Alembic by
setting both flags to `false` and running `alembic upgrade head`.
