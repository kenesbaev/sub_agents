from __future__ import annotations

import asyncio
import logging
import signal

from app.config import get_settings
from app.db.session import SessionLocal, engine
from app.health import readiness_report
from app.scheduled_posts.runtime import run_scheduled_post_worker


logger = logging.getLogger(__name__)


async def run_worker() -> None:
    settings = get_settings()
    if not settings.scheduled_post_worker_enabled:
        raise RuntimeError("SCHEDULED_POST_WORKER_ENABLED must be true for the dedicated worker")

    ready, _ = readiness_report(engine)
    if not ready:
        raise RuntimeError("database is not ready or Alembic migrations are not at head")

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signal_name in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(signal_name, stop_event.set)
        except (NotImplementedError, RuntimeError):
            pass

    logger.info("scheduled post worker started")
    await run_scheduled_post_worker(stop_event, settings, SessionLocal)
    logger.info("scheduled post worker stopped")


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    try:
        asyncio.run(run_worker())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
