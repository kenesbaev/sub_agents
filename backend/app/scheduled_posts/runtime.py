from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable

from sqlalchemy.orm import Session

from app.config import Settings
from app.scheduled_posts.service import ScheduledPostBatchResult, process_scheduled_post_batch


logger = logging.getLogger(__name__)


async def run_scheduled_post_worker(
    stop_event: asyncio.Event,
    settings: Settings,
    session_factory: Callable[[], Session],
    *,
    processor: Callable[..., ScheduledPostBatchResult] = process_scheduled_post_batch,
) -> None:
    while not stop_event.is_set():
        try:
            result = await asyncio.to_thread(processor, session_factory, settings)
            if result.claimed or result.stale_reconciled:
                logger.info(
                    "scheduled_post_worker_batch",
                    extra={
                        "claimed": result.claimed,
                        "published": result.published,
                        "retried": result.retried,
                        "failed": result.failed,
                        "reconciliation_required": result.reconciliation_required,
                        "stale_reconciled": result.stale_reconciled,
                    },
                )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.error("scheduled_post_worker_batch_failed", extra={"error_code": "worker_batch_failed"})

        try:
            await asyncio.wait_for(
                stop_event.wait(),
                timeout=settings.scheduled_post_worker_poll_seconds,
            )
        except TimeoutError:
            pass
