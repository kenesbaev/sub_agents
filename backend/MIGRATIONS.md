# Rebly AI Database Migrations

Phase 1 adds Alembic while keeping the existing startup `Base.metadata.create_all(bind=engine)` for backward compatibility.

## Local Commands

Run these commands from the `backend` directory:

```powershell
alembic current
alembic upgrade head
alembic history
```

## Existing Database Strategy

The first revision, `0001_existing_schema_baseline`, is defensive. It creates the legacy tables only when they are missing, so existing data is preserved.

The second revision, `0002_core_domain_foundation`, adds:

- `workspaces`
- `workspace_members`
- `agents`
- `teams`
- `team_agents`
- `tasks`

It also backfills one default workspace and owner membership for every existing user.

## New Database Strategy

For a fresh database:

```powershell
alembic upgrade head
```

The legacy schema and the Phase 1 core domain schema will be created.

## When Can `create_all` Be Removed?

Do not remove `Base.metadata.create_all(bind=engine)` yet.

It can be removed after:

1. Production and staging databases have a valid Alembic version row.
2. `alembic upgrade head` succeeds in staging from a production-like snapshot.
3. Startup no longer depends on implicit table creation.
4. CI runs migrations before tests or deployment.

