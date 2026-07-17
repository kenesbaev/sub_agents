from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, text


logger = logging.getLogger(__name__)
BACKEND_ROOT = Path(__file__).resolve().parents[1]


def migration_heads() -> set[str]:
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    return set(ScriptDirectory.from_config(config).get_heads())


def readiness_report(engine: Engine) -> tuple[bool, dict[str, Any]]:
    try:
        expected_heads = migration_heads()
    except Exception as exc:
        logger.error("migration readiness configuration failed (%s)", type(exc).__name__)
        return False, {
            "status": "not_ready",
            "checks": {
                "database": {"status": "unknown"},
                "migrations": {"status": "configuration_error", "expected": [], "current": []},
            },
        }
    report: dict[str, Any] = {
        "status": "not_ready",
        "checks": {
            "database": {"status": "unavailable"},
            "migrations": {
                "status": "unknown",
                "expected": sorted(expected_heads),
                "current": [],
            },
        },
    }
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
            report["checks"]["database"] = {"status": "ok"}
            current_heads = set(MigrationContext.configure(connection).get_current_heads())
    except Exception as exc:
        logger.warning("database readiness check failed (%s)", type(exc).__name__)
        return False, report

    migrations_ready = bool(current_heads) and current_heads == expected_heads
    report["checks"]["migrations"] = {
        "status": "ok" if migrations_ready else "out_of_date",
        "expected": sorted(expected_heads),
        "current": sorted(current_heads),
    }
    if migrations_ready:
        report["status"] = "ready"
    return migrations_ready, report
