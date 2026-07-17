from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import YouTubeApiCache


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


class YouTubePersistentCache:
    """Small DB-backed TTL cache. Cache keys never contain OAuth/API secrets."""

    def __init__(
        self,
        db: Session,
        *,
        ttl_seconds: int,
        workspace_id: int | None = None,
        integration_account_id: int | None = None,
    ) -> None:
        self.db = db
        self.ttl_seconds = ttl_seconds
        self.workspace_id = workspace_id
        self.integration_account_id = integration_account_id

    def key(self, namespace: str, payload: dict[str, Any], *, private: bool) -> str:
        scope = {
            "workspace": self.workspace_id if private else None,
            "account": self.integration_account_id if private else None,
        }
        material = json.dumps(
            {"namespace": namespace, "payload": payload, "scope": scope},
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
        return hashlib.sha256(material.encode("utf-8")).hexdigest()

    def get(self, cache_key: str) -> dict[str, Any] | None:
        record = self.db.scalar(select(YouTubeApiCache).where(YouTubeApiCache.cache_key == cache_key))
        if record is None:
            return None
        if _utc(record.expires_at) <= datetime.now(UTC):
            self.db.delete(record)
            self.db.flush()
            return None
        return dict(record.response_json)

    def set(
        self,
        cache_key: str,
        namespace: str,
        response: dict[str, Any],
        *,
        quota_cost: int,
        private: bool,
        ttl_seconds: int | None = None,
    ) -> None:
        record = self.db.scalar(select(YouTubeApiCache).where(YouTubeApiCache.cache_key == cache_key))
        expires_at = datetime.now(UTC) + timedelta(seconds=ttl_seconds or self.ttl_seconds)
        if record is None:
            record = YouTubeApiCache(cache_key=cache_key, namespace=namespace, response_json=response, expires_at=expires_at)
            self.db.add(record)
        record.namespace = namespace
        record.workspace_id = self.workspace_id if private else None
        record.integration_account_id = self.integration_account_id if private else None
        record.response_json = response
        record.expires_at = expires_at
        record.quota_cost = max(0, quota_cost)
        self.db.flush()
