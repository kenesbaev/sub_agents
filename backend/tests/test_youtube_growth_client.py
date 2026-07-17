from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.config import Settings  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.models import YouTubeApiCache  # noqa: E402
from app.youtube_growth.client import YouTubeClient  # noqa: E402
from app.youtube_growth.errors import (  # noqa: E402
    CaptionsUnavailableError,
    YouTubeQuotaError,
    YouTubeTimeoutError,
)


class FakeAsyncClient:
    responses: list[object] = []
    calls: list[dict] = []

    def __init__(self, *args, **kwargs) -> None:
        self.args = args
        self.kwargs = kwargs

    async def __aenter__(self) -> "FakeAsyncClient":
        return self

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        return None

    async def get(self, url: str, **kwargs):
        self.__class__.calls.append({"url": url, **kwargs})
        response = self.__class__.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class YouTubeClientTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(bind=self.engine)
        self.db = Session(self.engine)
        self.settings = Settings(
            database_url="sqlite+pysqlite:///:memory:",
            youtube_api_key="public-api-key",
            youtube_max_retries=1,
            youtube_retry_base_seconds=0,
            youtube_cache_ttl_seconds=300,
            youtube_max_pages=3,
        )
        self.client = YouTubeClient(self.db, self.settings, workspace_id=1)
        FakeAsyncClient.responses = []
        FakeAsyncClient.calls = []

    def tearDown(self) -> None:
        self.db.close()
        Base.metadata.drop_all(bind=self.engine)
        self.engine.dispose()

    async def test_public_response_is_persistently_cached_without_api_key_in_cache_key(self) -> None:
        FakeAsyncClient.responses = [
            httpx.Response(
                200,
                json={"items": [{"id": "video01", "statistics": {"viewCount": "0"}}]},
            )
        ]
        with patch("app.youtube_growth.client.httpx.AsyncClient", FakeAsyncClient):
            first = await self.client.get_video("video01")
            second = await self.client.get_video("video01")

        self.assertEqual("0", first["statistics"]["viewCount"])
        self.assertEqual(first, second)
        self.assertEqual(1, len(FakeAsyncClient.calls))
        cache_record = self.db.scalar(select(YouTubeApiCache))
        self.assertIsNotNone(cache_record)
        self.assertNotIn("public-api-key", cache_record.cache_key)

    async def test_oauth_fallback_cache_is_scoped_per_workspace_and_account(self) -> None:
        oauth_settings = Settings(
            database_url="sqlite+pysqlite:///:memory:",
            youtube_api_key="",
            youtube_cache_ttl_seconds=300,
        )
        first_client = YouTubeClient(
            self.db,
            oauth_settings,
            workspace_id=11,
            integration_account_id=101,
            access_token="first-token",
        )
        second_client = YouTubeClient(
            self.db,
            oauth_settings,
            workspace_id=22,
            integration_account_id=202,
            access_token="second-token",
        )
        FakeAsyncClient.responses = [
            httpx.Response(200, json={"items": [video]})
            for video in (
                {"id": "video01", "snippet": {"title": "Workspace one"}},
                {"id": "video01", "snippet": {"title": "Workspace two"}},
            )
        ]
        with patch("app.youtube_growth.client.httpx.AsyncClient", FakeAsyncClient):
            first = await first_client.get_video("video01")
            second = await second_client.get_video("video01")

        self.assertEqual("Workspace one", first["snippet"]["title"])
        self.assertEqual("Workspace two", second["snippet"]["title"])
        self.assertEqual(2, len(FakeAsyncClient.calls))
        self.assertEqual(2, len(self.db.scalars(select(YouTubeApiCache)).all()))
        self.assertEqual("Bearer first-token", FakeAsyncClient.calls[0]["headers"]["Authorization"])
        self.assertEqual("Bearer second-token", FakeAsyncClient.calls[1]["headers"]["Authorization"])

    async def test_owned_video_lookup_forces_oauth_even_when_api_key_exists(self) -> None:
        owned_client = YouTubeClient(
            self.db,
            self.settings,
            workspace_id=1,
            integration_account_id=7,
            access_token="owner-token",
        )
        FakeAsyncClient.responses = [httpx.Response(200, json={"items": [{"id": "video01"}]})]
        with patch("app.youtube_growth.client.httpx.AsyncClient", FakeAsyncClient):
            await owned_client.get_video("video01", require_oauth=True)
        call = FakeAsyncClient.calls[0]
        self.assertEqual("Bearer owner-token", call["headers"]["Authorization"])
        self.assertNotIn("key", call["params"])

    async def test_quota_exceeded_is_a_retryable_domain_error(self) -> None:
        response = httpx.Response(
            403,
            json={"error": {"errors": [{"reason": "quotaExceeded"}]}},
        )
        FakeAsyncClient.responses = [response, response]
        self.client._backoff = AsyncMock()  # type: ignore[method-assign]
        with patch("app.youtube_growth.client.httpx.AsyncClient", FakeAsyncClient):
            with self.assertRaises(YouTubeQuotaError) as raised:
                await self.client.get_video("video01")
        self.assertTrue(raised.exception.retryable)
        self.assertEqual(1, len(FakeAsyncClient.calls))

    async def test_timeout_retries_once_then_fails_without_network_in_test(self) -> None:
        FakeAsyncClient.responses = [httpx.ReadTimeout("slow"), httpx.ReadTimeout("still slow")]
        self.client._backoff = AsyncMock()  # type: ignore[method-assign]
        with patch("app.youtube_growth.client.httpx.AsyncClient", FakeAsyncClient):
            with self.assertRaises(YouTubeTimeoutError):
                await self.client.get_video("video01")
        self.assertEqual(2, len(FakeAsyncClient.calls))
        self.client._backoff.assert_awaited_once()

    async def test_pagination_stops_at_requested_limit_and_max_page_bound(self) -> None:
        self.client._request_json = AsyncMock(  # type: ignore[method-assign]
            side_effect=[
                {"items": [{"id": 1}, {"id": 2}], "nextPageToken": "page-two"},
                {"items": [{"id": 3}, {"id": 4}], "nextPageToken": "page-three"},
            ]
        )
        items = await self.client._paginate(
            "search",
            params={"part": "snippet"},
            namespace="test.pagination",
            max_items=3,
        )
        self.assertEqual([1, 2, 3], [item["id"] for item in items])
        self.assertEqual(2, self.client._request_json.await_count)

    async def test_caption_permission_failure_maps_to_captions_unavailable(self) -> None:
        oauth_client = YouTubeClient(
            self.db,
            self.settings,
            workspace_id=1,
            integration_account_id=9,
            access_token="oauth-token",
        )
        response = httpx.Response(403, json={"error": {"errors": [{"reason": "forbidden"}]}})
        FakeAsyncClient.responses = [response, response]
        oauth_client._backoff = AsyncMock()  # type: ignore[method-assign]
        with patch("app.youtube_growth.client.httpx.AsyncClient", FakeAsyncClient):
            with self.assertRaises(CaptionsUnavailableError):
                await oauth_client.captions("video01")

    async def test_partial_api_payload_and_empty_rows_are_normal(self) -> None:
        self.client._request_json = AsyncMock(return_value={"items": None})  # type: ignore[method-assign]
        self.assertEqual([], await self.client.get_videos(["video01"]))

        oauth_client = YouTubeClient(
            self.db,
            self.settings,
            workspace_id=1,
            integration_account_id=9,
            access_token="oauth-token",
        )
        oauth_client._request_json = AsyncMock(  # type: ignore[method-assign]
            return_value={"columnHeaders": [{"name": "views"}], "rows": []}
        )
        rows = await oauth_client.analytics_report(
            start_date=__import__("datetime").date(2026, 1, 1),
            end_date=__import__("datetime").date(2026, 1, 2),
            metrics=["views"],
        )
        self.assertEqual([], rows)


if __name__ == "__main__":
    unittest.main()
