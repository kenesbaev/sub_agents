from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest
from alembic import command
from alembic.config import Config
from fastapi import HTTPException
from sqlalchemy import create_engine, select, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import sessionmaker

from app.config import Settings, get_settings
from app.db.base import Base
from app.integrations import publish_to_platform, validate_scheduled_publish_request
from app.models import (
    ActivityLog,
    IntegrationAccount,
    IntegrationProvider,
    IntegrationToken,
    ScheduledPost,
    User,
    UserIntegration,
)
from app.schemas import PublishSocialRequest, PublishTargetResult
from app.scheduled_posts.runtime import run_scheduled_post_worker
from app.scheduled_posts.service import (
    PREFLIGHT_RETRY_ERROR,
    PROVIDER_OUTCOME_ERROR,
    RECONCILIATION_STATUS,
    STALE_OUTCOME_ERROR,
    PermanentPreflightError,
    RetryablePreflightError,
    ScheduledPostBatchResult,
    claim_due_posts,
    due_posts_statement,
    process_scheduled_post_batch,
)
from app.token_crypto import encrypt_token


BACKEND_ROOT = Path(__file__).resolve().parents[1]


def test_scheduled_publish_request_is_normalized_and_fail_closed() -> None:
    aware = PublishSocialRequest(
        text="Scheduled content",
        platforms=["telegram"],
        publish_at="2026-07-20T14:00:00+05:00",
    )
    assert validate_scheduled_publish_request(aware, ["telegram"]) == datetime(
        2026, 7, 20, 9, 0, tzinfo=timezone.utc
    )
    assert PublishSocialRequest.model_validate(
        {
            "text": "x",
            "platforms": ["telegram"],
            "accountId": 42,
        }
    ).account_id == 42

    invalid_payloads = (
        PublishSocialRequest(text="x", platforms=["youtube"], publish_at="2026-07-20T09:00:00Z"),
        PublishSocialRequest(text="x", platforms=["telegram"], publish_at="2026-07-20T09:00:00"),
        PublishSocialRequest(
            text="x", platforms=["telegram"], publish_at="2026-07-20T09:00:00Z", repeat_rule="daily"
        ),
        PublishSocialRequest(text="x", platforms=["instagram"], publish_at="2026-07-20T09:00:00Z"),
        PublishSocialRequest(
            text="x",
            platforms=["telegram"],
            publish_at="2026-07-20T09:00:00Z",
            media_data_url="data:image/png;base64,AA==",
        ),
    )
    for payload in invalid_payloads:
        with pytest.raises(HTTPException) as exc_info:
            validate_scheduled_publish_request(payload, list(payload.platforms))
        assert exc_info.value.status_code == 422


@pytest.fixture
def worker_database(tmp_path: Path):
    database_url = f"sqlite:///{tmp_path / 'worker.db'}"
    engine = create_engine(database_url, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    with session_factory() as db:
        user = User(email="scheduler@example.com")
        db.add(user)
        db.commit()
        user_id = user.id
    settings = Settings(
        _env_file=None,
        app_env="test",
        database_url=database_url,
        scheduled_post_worker_enabled=True,
        scheduled_post_worker_poll_seconds=1,
        scheduled_post_worker_batch_size=10,
        scheduled_post_worker_max_attempts=3,
        scheduled_post_worker_retry_base_seconds=10,
        scheduled_post_worker_retry_max_seconds=40,
        scheduled_post_worker_claim_stale_seconds=300,
    )
    try:
        yield session_factory, settings, user_id
    finally:
        engine.dispose()


def create_due_post(session_factory, user_id: int, now: datetime, *, platform: str = "telegram") -> int:
    with session_factory() as db:
        post = ScheduledPost(
            user_id=user_id,
            platform=platform,
            content="Scheduled content",
            publish_at=now - timedelta(seconds=1),
            timezone="UTC",
            status="scheduled",
            source="test",
        )
        db.add(post)
        db.commit()
        return post.id


def no_preflight(_db, _post) -> None:
    return None


def test_postgres_claim_uses_skip_locked() -> None:
    statement = due_posts_statement(datetime.now(timezone.utc), 10)
    sql = str(statement.compile(dialect=postgresql.dialect())).upper()

    assert "FOR UPDATE SKIP LOCKED" in sql


def test_claim_is_visible_to_second_worker(worker_database) -> None:
    session_factory, settings, user_id = worker_database
    now = datetime.now(timezone.utc)
    post_id = create_due_post(session_factory, user_id, now)

    first = claim_due_posts(session_factory, settings, now=now, worker_id="worker-one")
    second = claim_due_posts(session_factory, settings, now=now, worker_id="worker-two")

    assert [claim.post_id for claim in first] == [post_id]
    assert second == []
    with session_factory() as db:
        post = db.get(ScheduledPost, post_id)
        assert post.status == "processing"
        assert post.attempts == 1
        assert post.claim_token.startswith("worker-one:")


def test_success_is_committed_once_with_external_id(worker_database) -> None:
    session_factory, settings, user_id = worker_database
    now = datetime.now(timezone.utc)
    post_id = create_due_post(session_factory, user_id, now)
    calls: list[int] = []

    def publisher(_db, _user, **_kwargs):
        calls.append(1)
        return PublishTargetResult(platform="telegram", ok=True, external_id="message-42")

    result = process_scheduled_post_batch(
        session_factory,
        settings,
        now=now,
        worker_id="success-worker",
        publisher=publisher,
        preflight=no_preflight,
    )

    assert result.published == 1
    assert calls == [1]
    with session_factory() as db:
        post = db.get(ScheduledPost, post_id)
        assert post.status == "published"
        assert post.external_id == "message-42"
        assert post.claim_token is None
        activity = db.scalar(
            select(ActivityLog).where(
                ActivityLog.action == "publish_scheduled_post",
                ActivityLog.status == "published",
            )
        )
        assert activity is not None
        assert activity.metadata_json == {"scheduledPostId": post_id, "attempt": 1}


def test_selected_account_is_owned_validated_and_forwarded(worker_database) -> None:
    session_factory, settings, user_id = worker_database
    now = datetime.now(timezone.utc)
    with session_factory() as db:
        provider = IntegrationProvider(key="telegram", name="Telegram", auth_type="bot_token")
        db.add(provider)
        db.flush()
        integration = UserIntegration(user_id=user_id, provider_id=provider.id, status="connected")
        db.add(integration)
        db.flush()
        account = IntegrationAccount(
            user_integration_id=integration.id,
            provider_id=provider.id,
            account_identifier="-100123456",
            account_label="Production channel",
            account_type="channel",
            is_default=True,
        )
        db.add(account)
        db.flush()
        db.add(
            IntegrationToken(
                user_integration_id=integration.id,
                integration_account_id=account.id,
                encrypted_access_token=encrypt_token("123456789:test-bot-token"),
            )
        )
        post = ScheduledPost(
            user_id=user_id,
            platform="telegram",
            account_id=account.id,
            content="Scheduled content",
            publish_at=now - timedelta(seconds=1),
            timezone="UTC",
            status="scheduled",
            source="test",
        )
        db.add(post)
        db.commit()
        post_id = post.id
        account_id = account.id

    seen_account_ids: list[int | None] = []

    def publisher(_db, _user, **kwargs):
        seen_account_ids.append(kwargs.get("account_id"))
        return PublishTargetResult(platform="telegram", ok=True, external_id="message-account")

    result = process_scheduled_post_batch(
        session_factory,
        settings,
        now=now,
        publisher=publisher,
    )

    assert result.published == 1
    assert seen_account_ids == [account_id]
    with session_factory() as db:
        assert db.get(ScheduledPost, post_id).status == "published"


def test_immediate_publish_uses_users_default_connected_account(worker_database) -> None:
    session_factory, _settings, user_id = worker_database
    with session_factory() as db:
        provider = IntegrationProvider(key="telegram", name="Telegram", auth_type="bot_token")
        db.add(provider)
        db.flush()
        integration = UserIntegration(user_id=user_id, provider_id=provider.id, status="connected")
        db.add(integration)
        db.flush()
        account = IntegrationAccount(
            user_integration_id=integration.id,
            provider_id=provider.id,
            account_identifier="-100-default-channel",
            account_label="Default channel",
            account_type="channel",
            is_default=True,
        )
        db.add(account)
        db.flush()
        db.add(
            IntegrationToken(
                user_integration_id=integration.id,
                integration_account_id=account.id,
                encrypted_access_token=encrypt_token("default-bot-token"),
            )
        )
        db.commit()
        user = db.get(User, user_id)

        with patch("app.integrations.send_telegram_post", return_value={"message_id": 73}) as sender:
            result = publish_to_platform(
                db,
                user,
                platform="telegram",
                text="Approved message",
                media_url=None,
                media_data_url=None,
                media_type=None,
                media_name=None,
                run_id="run-default-account",
                source="test",
            )

        assert result.ok is True
        assert result.external_id == 73
        assert sender.call_args.args[:3] == (
            "default-bot-token",
            "-100-default-channel",
            "Approved message",
        )


def test_only_preflight_failure_retries_with_backoff_then_fails(worker_database) -> None:
    session_factory, settings, user_id = worker_database
    now = datetime.now(timezone.utc)
    post_id = create_due_post(session_factory, user_id, now)
    publish_calls: list[int] = []

    def transient_preflight(_db, _post) -> None:
        raise RetryablePreflightError("secret=must-not-be-persisted")

    def publisher(_db, _user, **_kwargs):
        publish_calls.append(1)
        return PublishTargetResult(platform="telegram", ok=True)

    first = process_scheduled_post_batch(
        session_factory,
        settings,
        now=now,
        publisher=publisher,
        preflight=transient_preflight,
    )
    assert first.retried == 1
    with session_factory() as db:
        post = db.get(ScheduledPost, post_id)
        assert post.status == "retry"
        assert post.error == PREFLIGHT_RETRY_ERROR
        first_retry_at = post.next_attempt_at.replace(tzinfo=timezone.utc)

    second = process_scheduled_post_batch(
        session_factory,
        settings,
        now=first_retry_at,
        publisher=publisher,
        preflight=transient_preflight,
    )
    assert second.retried == 1
    with session_factory() as db:
        post = db.get(ScheduledPost, post_id)
        second_retry_at = post.next_attempt_at.replace(tzinfo=timezone.utc)

    third = process_scheduled_post_batch(
        session_factory,
        settings,
        now=second_retry_at,
        publisher=publisher,
        preflight=transient_preflight,
    )
    assert third.failed == 1
    assert publish_calls == []
    with session_factory() as db:
        post = db.get(ScheduledPost, post_id)
        assert post.status == "failed"
        assert post.attempts == 3
        assert "must-not-be-persisted" not in (post.error or "")


def test_permanent_preflight_failure_never_calls_provider(worker_database) -> None:
    session_factory, settings, user_id = worker_database
    now = datetime.now(timezone.utc)
    post_id = create_due_post(session_factory, user_id, now, platform="linkedin")

    def permanent(_db, _post) -> None:
        raise PermanentPreflightError("This platform is not supported by scheduled publishing.")

    result = process_scheduled_post_batch(
        session_factory,
        settings,
        now=now,
        publisher=lambda *_args, **_kwargs: pytest.fail("provider must not be called"),
        preflight=permanent,
    )

    assert result.failed == 1
    with session_factory() as db:
        assert db.get(ScheduledPost, post_id).status == "failed"


@pytest.mark.parametrize("provider_mode", ["failed_result", "exception"])
def test_ambiguous_provider_outcome_requires_reconciliation_without_retry(
    worker_database,
    provider_mode: str,
) -> None:
    session_factory, settings, user_id = worker_database
    now = datetime.now(timezone.utc)
    post_id = create_due_post(session_factory, user_id, now)
    calls: list[int] = []

    def publisher(_db, _user, **_kwargs):
        calls.append(1)
        if provider_mode == "exception":
            raise RuntimeError("access_token=super-secret")
        return PublishTargetResult(platform="telegram", ok=False, error="token=super-secret")

    result = process_scheduled_post_batch(
        session_factory,
        settings,
        now=now,
        publisher=publisher,
        preflight=no_preflight,
    )
    second = process_scheduled_post_batch(
        session_factory,
        settings,
        now=now + timedelta(hours=1),
        publisher=publisher,
        preflight=no_preflight,
    )

    assert result.reconciliation_required == 1
    assert second.claimed == 0
    assert calls == [1]
    with session_factory() as db:
        post = db.get(ScheduledPost, post_id)
        assert post.status == RECONCILIATION_STATUS
        assert post.error == PROVIDER_OUTCOME_ERROR
        assert "super-secret" not in post.error


def test_stale_processing_claim_is_never_auto_retried(worker_database) -> None:
    session_factory, settings, user_id = worker_database
    now = datetime.now(timezone.utc)
    post_id = create_due_post(session_factory, user_id, now)
    with session_factory() as db:
        post = db.get(ScheduledPost, post_id)
        post.status = "processing"
        post.attempts = 1
        post.claimed_at = now - timedelta(seconds=settings.scheduled_post_worker_claim_stale_seconds + 1)
        post.claim_token = "dead-worker:claim"
        db.commit()

    result = process_scheduled_post_batch(
        session_factory,
        settings,
        now=now,
        publisher=lambda *_args, **_kwargs: pytest.fail("stale claim must not be re-sent"),
        preflight=no_preflight,
    )

    assert result.stale_reconciled == 1
    assert result.claimed == 0
    with session_factory() as db:
        post = db.get(ScheduledPost, post_id)
        assert post.status == RECONCILIATION_STATUS
        assert post.error == STALE_OUTCOME_ERROR


def test_worker_stops_without_starting_another_batch(worker_database) -> None:
    session_factory, settings, _user_id = worker_database
    calls: list[int] = []

    def processor(*_args, **_kwargs):
        calls.append(1)
        return ScheduledPostBatchResult()

    async def scenario() -> None:
        stop_event = asyncio.Event()
        stop_event.set()
        await run_scheduled_post_worker(stop_event, settings, session_factory, processor=processor)

    asyncio.run(scenario())
    assert calls == []


def test_0004_fails_closed_before_mutating_duplicate_connected_apps(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'duplicates.db'}"
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("DATABASE_URL", database_url)
    get_settings.cache_clear()
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    command.upgrade(config, "0003_youtube_growth_agent")

    engine = create_engine(database_url)
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO users (id, email) VALUES (1, 'duplicate@example.com')"))
        connection.execute(
            text(
                "INSERT INTO integration_providers (id, key, name, auth_type) "
                "VALUES (1, 'telegram', 'Telegram', 'api_key')"
            )
        )
        connection.execute(
            text(
                "INSERT INTO user_integrations (id, user_id, provider_id, status) VALUES "
                "(1, 1, 1, 'connected'), (2, 1, 1, 'connected')"
            )
        )
        connection.execute(
            text(
                "INSERT INTO integration_accounts "
                "(id, user_integration_id, provider_id, account_identifier, is_default) VALUES "
                "(1, 1, 1, 'same-account', 1), (2, 2, 1, 'same-account', 1)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO integration_tokens "
                "(id, user_integration_id, integration_account_id, encrypted_access_token) VALUES "
                "(1, 1, 1, 'older'), (2, 2, 2, 'newer')"
            )
        )

    with pytest.raises(RuntimeError, match="stopped before modifying data"):
        command.upgrade(config, "head")

    with engine.connect() as connection:
        assert connection.execute(text("SELECT COUNT(*) FROM user_integrations")).scalar_one() == 2
        assert connection.execute(text("SELECT COUNT(*) FROM integration_accounts")).scalar_one() == 2
        assert connection.execute(text("SELECT COUNT(*) FROM integration_tokens")).scalar_one() == 2
        assert connection.execute(text("SELECT COUNT(*) FROM scheduled_posts")).scalar_one() == 0
    engine.dispose()
    get_settings.cache_clear()
