from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, or_, select, update
from sqlalchemy.orm import Session

from app.config import Settings
from app.connected_apps.router import refresh_due_oauth_tokens
from app.core_domain.service import WRITE_ROLES
from app.models import (
    IntegrationAccount,
    IntegrationProvider,
    User,
    UserIntegration,
    WorkspaceMember,
    YouTubeGrowthSnapshot,
)
from app.youtube_growth.errors import YouTubeGrowthError
from app.youtube_growth.schemas import GrowthSnapshotCreateRequest, GrowthSnapshotResponse
from app.youtube_growth.service import create_growth_snapshot


logger = logging.getLogger(__name__)

SessionFactory = Callable[[], Session]
SnapshotHandler = Callable[
    [Session, Settings, User, int, GrowthSnapshotCreateRequest],
    Awaitable[GrowthSnapshotResponse],
]
OAuthRefresher = Callable[[Session, User], Awaitable[None]]


@dataclass(frozen=True)
class SnapshotProcessorResult:
    claimed: int = 0
    completed: int = 0
    deferred: int = 0
    failed: int = 0
    skipped: int = 0


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _candidate_ids(
    db: Session,
    *,
    now: datetime,
    stale_before: datetime,
    batch_size: int,
) -> list[int]:
    due = and_(
        YouTubeGrowthSnapshot.status == "queued",
        YouTubeGrowthSnapshot.scheduled_for.is_not(None),
        YouTubeGrowthSnapshot.scheduled_for <= now,
    )
    stale = and_(
        YouTubeGrowthSnapshot.status == "running",
        YouTubeGrowthSnapshot.updated_at <= stale_before,
    )
    return list(
        db.scalars(
            select(YouTubeGrowthSnapshot.id)
            .where(or_(due, stale))
            .order_by(YouTubeGrowthSnapshot.scheduled_for, YouTubeGrowthSnapshot.id)
            .limit(batch_size)
        ).all()
    )


def _claim_snapshot(
    db: Session,
    snapshot_id: int,
    *,
    now: datetime,
    stale_before: datetime,
) -> bool:
    due = and_(
        YouTubeGrowthSnapshot.status == "queued",
        YouTubeGrowthSnapshot.scheduled_for.is_not(None),
        YouTubeGrowthSnapshot.scheduled_for <= now,
    )
    stale = and_(
        YouTubeGrowthSnapshot.status == "running",
        YouTubeGrowthSnapshot.updated_at <= stale_before,
    )
    result = db.execute(
        update(YouTubeGrowthSnapshot)
        .where(YouTubeGrowthSnapshot.id == snapshot_id, or_(due, stale))
        .values(status="running", error_code=None, error=None, updated_at=now)
    )
    db.commit()
    return bool(result.rowcount)


def _load_processing_user(db: Session, snapshot: YouTubeGrowthSnapshot) -> User | None:
    if snapshot.created_by is None:
        return None
    membership = db.scalar(
        select(WorkspaceMember.id).where(
            WorkspaceMember.workspace_id == snapshot.workspace_id,
            WorkspaceMember.user_id == snapshot.created_by,
            WorkspaceMember.role.in_(WRITE_ROLES),
        )
    )
    if membership is None:
        return None
    owned_youtube_account = db.scalar(
        select(IntegrationAccount.id)
        .join(UserIntegration, UserIntegration.id == IntegrationAccount.user_integration_id)
        .join(IntegrationProvider, IntegrationProvider.id == IntegrationAccount.provider_id)
        .where(
            IntegrationAccount.id == snapshot.integration_account_id,
            UserIntegration.user_id == snapshot.created_by,
            IntegrationProvider.key == "youtube",
        )
    )
    if owned_youtube_account is None:
        return None
    return db.get(User, snapshot.created_by)


def _mark_failed(db: Session, snapshot_id: int, *, code: str, message: str, now: datetime) -> None:
    db.execute(
        update(YouTubeGrowthSnapshot)
        .where(YouTubeGrowthSnapshot.id == snapshot_id, YouTubeGrowthSnapshot.status == "running")
        .values(
            status="failed",
            error_code=code[:80],
            error=message,
            observed_at=now,
            updated_at=now,
        )
    )
    db.commit()


async def process_due_growth_snapshots(
    session_factory: SessionFactory,
    settings: Settings,
    *,
    now: datetime | None = None,
    batch_size: int | None = None,
    stale_seconds: int | None = None,
    snapshot_handler: SnapshotHandler = create_growth_snapshot,
    oauth_refresher: OAuthRefresher = refresh_due_oauth_tokens,
) -> SnapshotProcessorResult:
    fixed_time = _as_utc(now)
    scan_time = fixed_time or datetime.now(UTC)
    configured_batch_size = batch_size or settings.youtube_snapshot_worker_batch_size
    configured_stale_seconds = stale_seconds or settings.youtube_snapshot_worker_stale_seconds
    stale_before = scan_time - timedelta(seconds=configured_stale_seconds)

    with session_factory() as candidate_db:
        candidate_ids = _candidate_ids(
            candidate_db,
            now=scan_time,
            stale_before=stale_before,
            batch_size=configured_batch_size,
        )

    claimed = completed = deferred = failed = skipped = 0
    for snapshot_id in candidate_ids:
        claim_time = fixed_time or datetime.now(UTC)
        with session_factory() as claim_db:
            if not _claim_snapshot(claim_db, snapshot_id, now=claim_time, stale_before=stale_before):
                skipped += 1
                continue
        claimed += 1

        with session_factory() as db:
            workspace_id: int | None = None
            try:
                snapshot = db.get(YouTubeGrowthSnapshot, snapshot_id)
                if snapshot is None:
                    skipped += 1
                    continue
                workspace_id = snapshot.workspace_id
                user = _load_processing_user(db, snapshot)
                if user is None:
                    _mark_failed(
                        db,
                        snapshot_id,
                        code="invalid_snapshot_context",
                        message="Snapshot owner, workspace membership, or YouTube account is no longer valid.",
                        now=claim_time,
                    )
                    failed += 1
                    continue
                request = GrowthSnapshotCreateRequest(
                    workspace_id=snapshot.workspace_id,
                    account_id=snapshot.integration_account_id,
                    video_id=snapshot.video_id,
                    checkpoint=snapshot.checkpoint,
                )
                await oauth_refresher(db, user)
                db.commit()
                response = await snapshot_handler(db, settings, user, snapshot.workspace_id, request)
            except YouTubeGrowthError as exc:
                db.rollback()
                _mark_failed(db, snapshot_id, code=exc.code, message=exc.message, now=claim_time)
                failed += 1
                logger.info(
                    "youtube_snapshot_processing_failed",
                    extra={"snapshot_id": snapshot_id, "workspace_id": workspace_id, "error_code": exc.code},
                )
                continue
            except Exception:
                db.rollback()
                _mark_failed(
                    db,
                    snapshot_id,
                    code="snapshot_processing_failed",
                    message="Snapshot processing failed safely. Retry by creating a new checkpoint request if needed.",
                    now=claim_time,
                )
                failed += 1
                logger.error(
                    "youtube_snapshot_processing_failed",
                    extra={
                        "snapshot_id": snapshot_id,
                        "workspace_id": workspace_id,
                        "error_code": "snapshot_processing_failed",
                    },
                )
                continue

            if response.status in {"completed", "partial"}:
                completed += 1
            elif response.status == "queued":
                deferred += 1
            elif response.status == "failed":
                failed += 1
            else:
                # The service owns the row state. A running response is left leased and
                # becomes recoverable only after the configured stale timeout.
                deferred += 1

    return SnapshotProcessorResult(
        claimed=claimed,
        completed=completed,
        deferred=deferred,
        failed=failed,
        skipped=skipped,
    )
