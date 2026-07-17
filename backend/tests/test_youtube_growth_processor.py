from __future__ import annotations

import asyncio
import sys
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.config import Settings  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.models import (  # noqa: E402
    IntegrationAccount,
    IntegrationProvider,
    User,
    UserIntegration,
    Workspace,
    WorkspaceMember,
    YouTubeGrowthSnapshot,
)
from app.youtube_growth.errors import YouTubeQuotaError  # noqa: E402
from app.youtube_growth.processor import (  # noqa: E402
    SnapshotProcessorResult,
    process_due_growth_snapshots,
)
from app.youtube_growth.runtime import run_snapshot_worker  # noqa: E402
from app.youtube_growth.service import snapshot_response  # noqa: E402


class YouTubeGrowthProcessorTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(bind=self.engine)
        self.session_factory = sessionmaker(bind=self.engine, expire_on_commit=False)
        self.settings = Settings(
            database_url="sqlite+pysqlite:///:memory:",
            youtube_snapshot_worker_batch_size=10,
            youtube_snapshot_worker_stale_seconds=3600,
        )
        self.now = datetime(2026, 7, 16, 12, 0, tzinfo=UTC)
        with self.session_factory() as db:
            user = User(email="snapshot-owner@example.com")
            db.add(user)
            db.flush()
            workspace = Workspace(name="Owner workspace", slug="snapshot-owner", owner_id=user.id)
            db.add(workspace)
            db.flush()
            db.add(WorkspaceMember(workspace_id=workspace.id, user_id=user.id, role="owner"))
            provider = IntegrationProvider(
                key="youtube",
                name="YouTube",
                auth_type="oauth2",
                logo="youtube",
                docs_url="https://developers.google.com/youtube/v3",
            )
            db.add(provider)
            db.flush()
            integration = UserIntegration(user_id=user.id, provider_id=provider.id, status="connected")
            db.add(integration)
            db.flush()
            account = IntegrationAccount(
                user_integration_id=integration.id,
                provider_id=provider.id,
                account_identifier="UCsnapshotOwner01",
                account_label="Owner channel",
                account_type="youtube_channel",
            )
            db.add(account)
            db.commit()
            self.user_id = user.id
            self.workspace_id = workspace.id
            self.account_id = account.id

    def tearDown(self) -> None:
        self.engine.dispose()

    def add_snapshot(
        self,
        *,
        status: str = "queued",
        scheduled_for: datetime | None = None,
        updated_at: datetime | None = None,
        checkpoint: str = "1h",
    ) -> int:
        with self.session_factory() as db:
            snapshot = YouTubeGrowthSnapshot(
                workspace_id=self.workspace_id,
                created_by=self.user_id,
                integration_account_id=self.account_id,
                video_id=f"video-{checkpoint}",
                checkpoint=checkpoint,
                status=status,
                scheduled_for=scheduled_for or self.now - timedelta(minutes=1),
                updated_at=updated_at or self.now,
            )
            db.add(snapshot)
            db.commit()
            return snapshot.id

    async def completed_handler(self, db, _settings, _user, _workspace_id, request):
        snapshot = db.scalar(
            select(YouTubeGrowthSnapshot).where(
                YouTubeGrowthSnapshot.integration_account_id == request.account_id,
                YouTubeGrowthSnapshot.video_id == request.video_id,
                YouTubeGrowthSnapshot.checkpoint == request.checkpoint,
            )
        )
        snapshot.status = "completed"
        snapshot.metrics_json = {"views": 12}
        snapshot.baseline_json = {"sample_size": 0}
        snapshot.recommendations_json = []
        snapshot.limitations_json = []
        snapshot.observed_at = self.now
        db.commit()
        db.refresh(snapshot)
        return snapshot_response(snapshot)

    async def test_future_snapshot_is_not_claimed(self) -> None:
        snapshot_id = self.add_snapshot(scheduled_for=self.now + timedelta(hours=1))
        handler = AsyncMock(side_effect=self.completed_handler)

        result = await process_due_growth_snapshots(
            self.session_factory,
            self.settings,
            now=self.now,
            snapshot_handler=handler,
            oauth_refresher=AsyncMock(),
        )

        self.assertEqual(SnapshotProcessorResult(), result)
        handler.assert_not_awaited()
        with self.session_factory() as db:
            self.assertEqual("queued", db.get(YouTubeGrowthSnapshot, snapshot_id).status)

    async def test_due_snapshot_is_processed_once(self) -> None:
        snapshot_id = self.add_snapshot()
        handler = AsyncMock(side_effect=self.completed_handler)
        refresher = AsyncMock()

        first = await process_due_growth_snapshots(
            self.session_factory,
            self.settings,
            now=self.now,
            snapshot_handler=handler,
            oauth_refresher=refresher,
        )
        second = await process_due_growth_snapshots(
            self.session_factory,
            self.settings,
            now=self.now + timedelta(minutes=1),
            snapshot_handler=handler,
            oauth_refresher=refresher,
        )

        self.assertEqual(1, first.claimed)
        self.assertEqual(1, first.completed)
        self.assertEqual(0, second.claimed)
        handler.assert_awaited_once()
        refresher.assert_awaited_once()
        with self.session_factory() as db:
            self.assertEqual("completed", db.get(YouTubeGrowthSnapshot, snapshot_id).status)

    async def test_recent_running_claim_is_skipped_but_stale_claim_is_recovered(self) -> None:
        recent_id = self.add_snapshot(status="running", updated_at=self.now, checkpoint="6h")
        stale_id = self.add_snapshot(
            status="running",
            updated_at=self.now - timedelta(hours=2),
            checkpoint="24h",
        )
        handler = AsyncMock(side_effect=self.completed_handler)

        result = await process_due_growth_snapshots(
            self.session_factory,
            self.settings,
            now=self.now,
            snapshot_handler=handler,
            oauth_refresher=AsyncMock(),
        )

        self.assertEqual(1, result.claimed)
        with self.session_factory() as db:
            self.assertEqual("running", db.get(YouTubeGrowthSnapshot, recent_id).status)
            self.assertEqual("completed", db.get(YouTubeGrowthSnapshot, stale_id).status)

    async def test_removed_workspace_member_fails_before_refresh_or_api(self) -> None:
        snapshot_id = self.add_snapshot()
        with self.session_factory() as db:
            membership = db.scalar(
                select(WorkspaceMember).where(
                    WorkspaceMember.workspace_id == self.workspace_id,
                    WorkspaceMember.user_id == self.user_id,
                )
            )
            db.delete(membership)
            db.commit()
        handler = AsyncMock()
        refresher = AsyncMock()

        result = await process_due_growth_snapshots(
            self.session_factory,
            self.settings,
            now=self.now,
            snapshot_handler=handler,
            oauth_refresher=refresher,
        )

        self.assertEqual(1, result.failed)
        handler.assert_not_awaited()
        refresher.assert_not_awaited()
        with self.session_factory() as db:
            snapshot = db.get(YouTubeGrowthSnapshot, snapshot_id)
            self.assertEqual("failed", snapshot.status)
            self.assertEqual("invalid_snapshot_context", snapshot.error_code)

    async def test_read_only_workspace_member_cannot_run_a_due_snapshot(self) -> None:
        snapshot_id = self.add_snapshot(checkpoint="6h")
        with self.session_factory() as db:
            membership = db.scalar(
                select(WorkspaceMember).where(
                    WorkspaceMember.workspace_id == self.workspace_id,
                    WorkspaceMember.user_id == self.user_id,
                )
            )
            membership.role = "viewer"
            db.commit()
        handler = AsyncMock()
        refresher = AsyncMock()

        result = await process_due_growth_snapshots(
            self.session_factory,
            self.settings,
            now=self.now,
            snapshot_handler=handler,
            oauth_refresher=refresher,
        )

        self.assertEqual(1, result.failed)
        handler.assert_not_awaited()
        refresher.assert_not_awaited()
        with self.session_factory() as db:
            snapshot = db.get(YouTubeGrowthSnapshot, snapshot_id)
            self.assertEqual("failed", snapshot.status)
            self.assertEqual("invalid_snapshot_context", snapshot.error_code)

    async def test_domain_and_unexpected_errors_are_persisted_safely(self) -> None:
        domain_id = self.add_snapshot(checkpoint="72h")

        async def quota_handler(*_args):
            raise YouTubeQuotaError()

        domain_result = await process_due_growth_snapshots(
            self.session_factory,
            self.settings,
            now=self.now,
            snapshot_handler=quota_handler,
            oauth_refresher=AsyncMock(),
        )
        self.assertEqual(1, domain_result.failed)
        with self.session_factory() as db:
            domain_snapshot = db.get(YouTubeGrowthSnapshot, domain_id)
            self.assertEqual("quota_exceeded", domain_snapshot.error_code)
            self.assertNotIn("token", domain_snapshot.error.lower())

        unexpected_id = self.add_snapshot(checkpoint="7d")

        async def unsafe_handler(*_args):
            raise RuntimeError("access_token=do-not-store-this")

        unexpected_result = await process_due_growth_snapshots(
            self.session_factory,
            self.settings,
            now=self.now + timedelta(seconds=1),
            snapshot_handler=unsafe_handler,
            oauth_refresher=AsyncMock(),
        )
        self.assertEqual(1, unexpected_result.failed)
        with self.session_factory() as db:
            unexpected_snapshot = db.get(YouTubeGrowthSnapshot, unexpected_id)
            self.assertEqual("snapshot_processing_failed", unexpected_snapshot.error_code)
            self.assertNotIn("do-not-store-this", unexpected_snapshot.error)

    async def test_runtime_sleeps_before_first_poll_and_stops_cleanly(self) -> None:
        self.settings.youtube_snapshot_worker_poll_seconds = 0.03
        stop_event = asyncio.Event()
        processor = AsyncMock(return_value=SnapshotProcessorResult())
        task = asyncio.create_task(
            run_snapshot_worker(stop_event, self.settings, self.session_factory, processor=processor)
        )

        await asyncio.sleep(0)
        processor.assert_not_awaited()
        await asyncio.sleep(0.05)
        self.assertGreaterEqual(processor.await_count, 1)
        stop_event.set()
        await asyncio.wait_for(task, timeout=0.2)


if __name__ == "__main__":
    unittest.main()
