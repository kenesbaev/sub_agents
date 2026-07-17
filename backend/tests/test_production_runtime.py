from __future__ import annotations

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from pydantic import ValidationError
from sqlalchemy import UniqueConstraint, create_engine, text

from app import models
from app.config import Settings, get_settings
from app.db.base import Base
from app.db.session import create_database_engine
from app.health import migration_heads, readiness_report


BACKEND_ROOT = Path(__file__).resolve().parents[1]


def production_settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "app_env": "production",
        "database_url": "postgresql://rebly:secret@db.internal/rebly",
        "jwt_secret": "j" * 40,
        "integration_encryption_secret": "e" * 40,
        "access_token_minutes": 1440,
        "frontend_url": "https://app.example.com",
        "backend_url": "https://api.example.com",
        "google_client_id": "production-google-client-id.apps.googleusercontent.com",
        "google_client_secret": "production-google-client-secret",
        "google_redirect_uri": "https://api.example.com/api/auth/google/callback",
        "google_connected_redirect_uri": "https://api.example.com/api/connected-apps/google/callback",
        "cookie_secure": True,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def migration_config(monkeypatch: pytest.MonkeyPatch, database_url: str) -> Config:
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("DATABASE_URL", database_url)
    get_settings.cache_clear()
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    return config


def test_local_defaults_preserve_schema_bootstrap_compatibility() -> None:
    settings = Settings(_env_file=None, database_url="sqlite://")

    assert models.User.__tablename__ == "users"
    assert settings.auto_create_schema_enabled is True
    assert settings.startup_backfill_enabled is True


@pytest.mark.parametrize(
    ("table", "constraint_name", "columns"),
    [
        (models.User.__table__, "users_email_key", ("email",)),
        (models.User.__table__, "users_google_sub_key", ("google_sub",)),
        (
            models.TelegramBotIntegration.__table__,
            "telegram_bot_integrations_user_id_key",
            ("user_id",),
        ),
        (
            models.InstagramIntegration.__table__,
            "instagram_integrations_user_id_key",
            ("user_id",),
        ),
        (
            models.IntegrationProvider.__table__,
            "integration_providers_key_key",
            ("key",),
        ),
    ],
)
def test_legacy_unique_constraints_match_postgres_schema(
    table: object,
    constraint_name: str,
    columns: tuple[str, ...],
) -> None:
    constraints = {
        constraint.name: tuple(column.name for column in constraint.columns)
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint)
    }

    assert constraints[constraint_name] == columns
    assert any(
        index.unique and tuple(column.name for column in index.columns) == columns
        for index in table.indexes
    )


def test_valid_production_settings_disable_implicit_mutations() -> None:
    settings = production_settings()

    assert settings.auto_create_schema_enabled is False
    assert settings.startup_backfill_enabled is False
    assert settings.sqlalchemy_database_url == "postgresql+psycopg://rebly:secret@db.internal/rebly"
    assert settings.allowed_cors_origins() == ["https://app.example.com"]
    assert settings.allowed_hostnames() == ["api.example.com"]


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"jwt_secret": "replace-with-a-unique-random-secret-at-least-32-characters"}, "JWT_SECRET"),
        ({"integration_encryption_secret": "replace-with-a-different-random-secret-at-least-32-characters"}, "INTEGRATION_ENCRYPTION_SECRET"),
        ({"cookie_secure": False}, "COOKIE_SECURE"),
        ({"frontend_url": "http://127.0.0.1:3000"}, "FRONTEND_URL"),
        ({"database_url": "sqlite:///production.db"}, "DATABASE_URL"),
        ({"database_auto_create_schema": True}, "DATABASE_AUTO_CREATE_SCHEMA"),
        ({"database_startup_backfill": True}, "DATABASE_STARTUP_BACKFILL"),
        ({"youtube_snapshot_worker_run_in_api": True}, "YOUTUBE_SNAPSHOT_WORKER_RUN_IN_API"),
        ({"jwt_algorithm": "none"}, "JWT_ALGORITHM"),
        ({"trusted_hosts": "*"}, "trusted hosts"),
        ({"access_token_minutes": 1441}, "ACCESS_TOKEN_MINUTES"),
        ({"local_password_auth_enabled": True}, "LOCAL_PASSWORD_AUTH_ENABLED"),
        ({"youtube_upload_enabled": True}, "YOUTUBE_UPLOAD_ENABLED"),
        ({"google_client_secret": ""}, "GOOGLE_CLIENT_ID"),
        ({"google_redirect_uri": "http://api.example.com/api/auth/google/callback"}, "GOOGLE_REDIRECT_URI"),
        ({"scheduled_post_worker_batch_size": 2}, "SCHEDULED_POST_WORKER_BATCH_SIZE"),
    ],
)
def test_production_validation_rejects_unsafe_configuration(
    overrides: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(ValidationError, match=message):
        production_settings(**overrides)


def test_database_engine_applies_bounded_postgres_pool() -> None:
    settings = Settings(
        _env_file=None,
        database_url="postgresql://rebly:secret@127.0.0.1/rebly",
        database_pool_size=7,
        database_max_overflow=3,
        database_pool_timeout_seconds=12,
        database_pool_recycle_seconds=900,
    )

    engine = create_database_engine(settings)
    try:
        assert str(engine.url).startswith("postgresql+psycopg://")
        assert engine.pool.size() == 7
        assert engine.pool._max_overflow == 3  # noqa: SLF001 - verifies SQLAlchemy pool wiring
        assert engine.pool._timeout == 12  # noqa: SLF001 - verifies SQLAlchemy pool wiring
        assert engine.pool._recycle == 900  # noqa: SLF001 - verifies SQLAlchemy pool wiring
    finally:
        engine.dispose()


def test_readiness_fails_closed_before_migrations(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'empty.db'}")
    try:
        ready, report = readiness_report(engine)
    finally:
        engine.dispose()

    assert ready is False
    assert report["status"] == "not_ready"
    assert report["checks"]["database"] == {"status": "ok"}
    assert report["checks"]["migrations"]["status"] == "out_of_date"


def test_fresh_database_migrates_from_base_to_head(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'fresh.db'}"
    config = migration_config(monkeypatch, database_url)

    command.upgrade(config, "head")
    command.check(config)

    engine = create_engine(database_url)
    try:
        ready, report = readiness_report(engine)
    finally:
        engine.dispose()
        get_settings.cache_clear()

    assert ready is True
    assert report["checks"]["migrations"]["current"] == sorted(migration_heads())


def test_schema_contract_guard_rejects_incomplete_legacy_table(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'drift.db'}"
    config = migration_config(monkeypatch, database_url)
    command.upgrade(config, "0004_scheduled_post_delivery")

    engine = create_engine(database_url)
    with engine.begin() as connection:
        connection.execute(text("ALTER TABLE scheduled_posts DROP COLUMN media_type"))
    engine.dispose()

    with pytest.raises(RuntimeError, match="schema contract validation failed"):
        command.upgrade(config, "head")
    get_settings.cache_clear()


def test_existing_orm_database_is_adopted_without_data_loss(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'existing.db'}"
    engine = create_engine(database_url)
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO users (email) VALUES ('existing@example.com')"))
    engine.dispose()

    config = migration_config(monkeypatch, database_url)
    command.upgrade(config, "head")
    command.check(config)

    engine = create_engine(database_url)
    try:
        with engine.connect() as connection:
            assert connection.execute(text("SELECT COUNT(*) FROM users")).scalar_one() == 1
            assert connection.execute(text("SELECT COUNT(*) FROM workspace_members")).scalar_one() == 1
        ready, _ = readiness_report(engine)
    finally:
        engine.dispose()
        get_settings.cache_clear()

    assert ready is True
