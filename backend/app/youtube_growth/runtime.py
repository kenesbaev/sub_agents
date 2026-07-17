from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable

from sqlalchemy.orm import Session

from app.config import Settings
from app.youtube_growth.processor import SnapshotProcessorResult, process_due_growth_snapshots


logger = logging.getLogger(__name__)


async def run_snapshot_worker(
    stop_event: asyncio.Event,
    settings: Settings,
    session_factory: Callable[[], Session],
    *,
    processor: Callable[..., object] = process_due_growth_snapshots,
) -> None:
    poll_seconds = settings.youtube_snapshot_worker_poll_seconds
    while not stop_event.is_set():
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=poll_seconds)
            continue
        except TimeoutError:
            pass
        try:
            result = await processor(session_factory, settings)
            if isinstance(result, SnapshotProcessorResult) and result.claimed:
                logger.info(
                    "youtube_snapshot_worker_batch",
                    extra={
                        "claimed": result.claimed,
                        "completed": result.completed,
                        "deferred": result.deferred,
                        "failed": result.failed,
                        "skipped": result.skipped,
                    },
                )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.error("youtube_snapshot_worker_batch_failed", extra={"error_code": "worker_batch_failed"})
