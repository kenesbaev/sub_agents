from __future__ import annotations

import asyncio
import logging
import random
import re
from datetime import date
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
from sqlalchemy.orm import Session

from app.config import Settings
from app.youtube_growth.cache import YouTubePersistentCache
from app.youtube_growth.errors import (
    AnalyticsUnavailableError,
    CaptionsUnavailableError,
    CommentsDisabledError,
    YouTubeGrowthError,
    YouTubeNotConfiguredError,
    YouTubeNotFoundError,
    YouTubePermissionError,
    YouTubeQuotaError,
    YouTubeRateLimitError,
    YouTubeTimeoutError,
    YouTubeUpstreamError,
)


LOGGER = logging.getLogger("teamora.youtube_growth.client")
RETRYABLE_STATUS = {429, 500, 502, 503, 504}
VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{6,20}$")
CHANNEL_ID_RE = re.compile(r"^UC[A-Za-z0-9_-]{10,40}$")


def video_id_from_reference(value: str) -> str:
    raw = value.strip()
    if VIDEO_ID_RE.fullmatch(raw):
        return raw
    parsed = urlparse(raw if "://" in raw else f"https://{raw}")
    host = (parsed.hostname or "").lower().removeprefix("www.")
    video_id = ""
    if host == "youtu.be":
        video_id = parsed.path.strip("/").split("/", 1)[0]
    elif host in {"youtube.com", "m.youtube.com", "music.youtube.com"}:
        if parsed.path == "/watch":
            video_id = (parse_qs(parsed.query).get("v") or [""])[0]
        else:
            parts = [part for part in parsed.path.split("/") if part]
            if len(parts) >= 2 and parts[0] in {"shorts", "live", "embed"}:
                video_id = parts[1]
    if not VIDEO_ID_RE.fullmatch(video_id):
        raise YouTubeNotFoundError("Enter a valid YouTube video URL or video ID.")
    return video_id


def channel_reference(value: str) -> tuple[str, str]:
    raw = value.strip()
    if CHANNEL_ID_RE.fullmatch(raw):
        return "id", raw
    if raw.startswith("@") and len(raw) > 1:
        return "handle", raw[1:]
    parsed = urlparse(raw if "://" in raw else f"https://{raw}")
    host = (parsed.hostname or "").lower().removeprefix("www.")
    if host not in {"youtube.com", "m.youtube.com"}:
        raise YouTubeNotFoundError("Enter a valid YouTube channel URL, handle, or channel ID.")
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) >= 2 and parts[0] == "channel" and CHANNEL_ID_RE.fullmatch(parts[1]):
        return "id", parts[1]
    if parts and parts[0].startswith("@"):
        return "handle", parts[0][1:]
    if len(parts) >= 2 and parts[0] in {"user", "c"}:
        return "query", parts[1]
    raise YouTubeNotFoundError("Enter a valid YouTube channel URL, handle, or channel ID.")


def _reason(payload: object) -> str:
    if not isinstance(payload, dict):
        return ""
    error = payload.get("error")
    if not isinstance(error, dict):
        return ""
    errors = error.get("errors")
    if isinstance(errors, list) and errors and isinstance(errors[0], dict):
        return str(errors[0].get("reason") or "")
    return str(error.get("status") or "")


class YouTubeClient:
    def __init__(
        self,
        db: Session,
        settings: Settings,
        *,
        workspace_id: int,
        integration_account_id: int | None = None,
        access_token: str | None = None,
    ) -> None:
        self.db = db
        self.settings = settings
        self.workspace_id = workspace_id
        self.integration_account_id = integration_account_id
        self.access_token = access_token or ""
        self.api_key = settings.youtube_api_key.strip()
        self.cache = YouTubePersistentCache(
            db,
            ttl_seconds=settings.youtube_cache_ttl_seconds,
            workspace_id=workspace_id,
            integration_account_id=integration_account_id,
        )

    @property
    def has_data_api_credentials(self) -> bool:
        return bool(self.api_key or self.access_token)

    def _auth(self, *, require_oauth: bool) -> tuple[dict[str, str], dict[str, str]]:
        if require_oauth:
            if not self.access_token:
                raise YouTubePermissionError("This operation requires an authorized YouTube channel.")
            return {"Authorization": f"Bearer {self.access_token}"}, {}
        if self.api_key:
            return {}, {"key": self.api_key}
        if self.access_token:
            return {"Authorization": f"Bearer {self.access_token}"}, {}
        raise YouTubeNotConfiguredError()

    async def _request_json(
        self,
        base_url: str,
        path: str,
        *,
        params: dict[str, Any],
        namespace: str,
        quota_cost: int = 1,
        require_oauth: bool = False,
        private_cache: bool | None = None,
    ) -> dict[str, Any]:
        headers, auth_params = self._auth(require_oauth=require_oauth)
        request_params = {**params, **auth_params}
        cache_payload = {key: value for key, value in params.items() if value is not None}
        uses_oauth = require_oauth or (not self.api_key and bool(self.access_token))
        private = uses_oauth if private_cache is None else (uses_oauth or private_cache)
        cache_key = self.cache.key(namespace, cache_payload, private=private)
        cached = self.cache.get(cache_key)
        if cached is not None:
            LOGGER.info("youtube_api_cache_hit", extra={"path": path, "namespace": namespace, "quota_cost": quota_cost})
            return cached

        url = f"{base_url.rstrip('/')}/{path.lstrip('/')}"
        timeout = httpx.Timeout(self.settings.youtube_http_timeout_seconds)
        last_error: Exception | None = None
        for attempt in range(self.settings.youtube_max_retries + 1):
            try:
                async with httpx.AsyncClient(timeout=timeout) as client:
                    response = await client.get(url, params=request_params, headers={**headers, "Accept": "application/json"})
            except httpx.TimeoutException as exc:
                last_error = exc
                if attempt < self.settings.youtube_max_retries:
                    await self._backoff(attempt, None)
                    continue
                raise YouTubeTimeoutError() from exc
            except httpx.HTTPError as exc:
                last_error = exc
                if attempt < self.settings.youtube_max_retries:
                    await self._backoff(attempt, None)
                    continue
                raise YouTubeUpstreamError() from exc

            if response.status_code in RETRYABLE_STATUS and attempt < self.settings.youtube_max_retries:
                await self._backoff(attempt, response.headers.get("retry-after"))
                continue
            payload = self._json(response)
            if response.status_code >= 400:
                self._raise_api_error(response.status_code, payload, namespace)
            if not isinstance(payload, dict):
                raise YouTubeUpstreamError("YouTube API returned an invalid response.", retryable=False)
            self.cache.set(cache_key, namespace, payload, quota_cost=quota_cost, private=private)
            LOGGER.info(
                "youtube_api_request",
                extra={"path": path, "namespace": namespace, "status": response.status_code, "quota_cost": quota_cost},
            )
            return payload
        raise YouTubeUpstreamError() from last_error

    async def _request_text(
        self,
        path: str,
        *,
        params: dict[str, Any],
        namespace: str,
    ) -> str:
        headers, _auth_params = self._auth(require_oauth=True)
        cache_key = self.cache.key(namespace, params, private=True)
        cached = self.cache.get(cache_key)
        if cached is not None:
            return str(cached.get("text") or "")
        url = f"{self.settings.youtube_data_api_base_url.rstrip('/')}/{path.lstrip('/')}"
        timeout = httpx.Timeout(self.settings.youtube_http_timeout_seconds)
        for attempt in range(self.settings.youtube_max_retries + 1):
            try:
                async with httpx.AsyncClient(timeout=timeout) as client:
                    response = await client.get(url, params=params, headers=headers)
            except httpx.TimeoutException as exc:
                if attempt < self.settings.youtube_max_retries:
                    await self._backoff(attempt, None)
                    continue
                raise YouTubeTimeoutError() from exc
            except httpx.HTTPError as exc:
                if attempt < self.settings.youtube_max_retries:
                    await self._backoff(attempt, None)
                    continue
                raise YouTubeUpstreamError() from exc
            if response.status_code in RETRYABLE_STATUS and attempt < self.settings.youtube_max_retries:
                await self._backoff(attempt, response.headers.get("retry-after"))
                continue
            if response.status_code >= 400:
                try:
                    payload = response.json()
                except ValueError:
                    payload = {}
                self._raise_api_error(response.status_code, payload, namespace)
            text = response.text[:200_000]
            self.cache.set(cache_key, namespace, {"text": text}, quota_cost=200, private=True)
            return text
        raise YouTubeUpstreamError()

    @staticmethod
    def _json(response: httpx.Response) -> object:
        try:
            return response.json() if response.content else {}
        except ValueError as exc:
            raise YouTubeUpstreamError("YouTube API returned invalid JSON.", retryable=False) from exc

    async def _backoff(self, attempt: int, retry_after: str | None) -> None:
        seconds = 0.0
        if retry_after:
            try:
                seconds = max(0.0, min(30.0, float(retry_after)))
            except ValueError:
                seconds = 0.0
        if seconds <= 0:
            base = self.settings.youtube_retry_base_seconds * (2**attempt)
            seconds = min(30.0, base + random.uniform(0, max(0.001, base / 4)))
        await asyncio.sleep(seconds)

    @staticmethod
    def _raise_api_error(status_code: int, payload: object, namespace: str) -> None:
        reason = _reason(payload).lower()
        if reason in {"quotaexceeded", "dailylimitexceeded"}:
            raise YouTubeQuotaError()
        if reason in {"ratelimitexceeded", "userratelimitexceeded"} or status_code == 429:
            raise YouTubeRateLimitError()
        if reason == "commentsdisabled":
            raise CommentsDisabledError()
        if namespace.startswith("captions"):
            raise CaptionsUnavailableError()
        if namespace.startswith("analytics") and status_code in {400, 403, 404}:
            raise AnalyticsUnavailableError()
        if status_code in {401, 403}:
            raise YouTubePermissionError()
        if status_code == 404:
            raise YouTubeNotFoundError()
        if status_code >= 500:
            raise YouTubeUpstreamError()
        raise YouTubeGrowthError("youtube_request_rejected", "YouTube rejected the request.", 400, False)

    async def _paginate(
        self,
        path: str,
        *,
        params: dict[str, Any],
        namespace: str,
        max_items: int,
        quota_cost: int = 1,
        require_oauth: bool = False,
    ) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        page_token: str | None = None
        for page in range(self.settings.youtube_max_pages):
            page_params = {**params, "maxResults": min(50, max_items - len(items))}
            if page_token:
                page_params["pageToken"] = page_token
            payload = await self._request_json(
                self.settings.youtube_data_api_base_url,
                path,
                params=page_params,
                namespace=f"{namespace}:page:{page}",
                quota_cost=quota_cost,
                require_oauth=require_oauth,
            )
            page_items = payload.get("items") if isinstance(payload.get("items"), list) else []
            items.extend(item for item in page_items if isinstance(item, dict))
            if len(items) >= max_items:
                break
            page_token = str(payload.get("nextPageToken") or "") or None
            if not page_token:
                break
        return items[:max_items]

    async def get_video(self, video_id: str, *, require_oauth: bool = False) -> dict[str, Any]:
        items = await self.get_videos([video_id], require_oauth=require_oauth)
        if not items:
            raise YouTubeNotFoundError("The YouTube video was not found or is not public.")
        return items[0]

    async def get_videos(self, video_ids: list[str], *, require_oauth: bool = False) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for start in range(0, len(video_ids), 50):
            chunk = video_ids[start : start + 50]
            payload = await self._request_json(
                self.settings.youtube_data_api_base_url,
                "videos",
                params={"part": "snippet,statistics,contentDetails,status", "id": ",".join(chunk), "maxResults": len(chunk)},
                namespace="videos.list",
                require_oauth=require_oauth,
            )
            items = payload.get("items") if isinstance(payload.get("items"), list) else []
            result.extend(item for item in items if isinstance(item, dict))
        return result

    async def resolve_channel(self, reference: str) -> dict[str, Any]:
        kind, value = channel_reference(reference)
        if kind in {"id", "handle"}:
            params: dict[str, Any] = {"part": "snippet,statistics,contentDetails,brandingSettings", "maxResults": 1}
            params["id" if kind == "id" else "forHandle"] = value
            payload = await self._request_json(
                self.settings.youtube_data_api_base_url,
                "channels",
                params=params,
                namespace="channels.resolve",
            )
            items = payload.get("items") if isinstance(payload.get("items"), list) else []
            if items and isinstance(items[0], dict):
                return items[0]
        search = await self._paginate(
            "search",
            params={"part": "snippet", "type": "channel", "q": value},
            namespace="search.channels",
            max_items=1,
            quota_cost=100,
        )
        channel_id = ""
        if search:
            raw_id = search[0].get("id")
            channel_id = str(raw_id.get("channelId") or "") if isinstance(raw_id, dict) else ""
        if not channel_id:
            raise YouTubeNotFoundError("The YouTube channel was not found.")
        return await self.resolve_channel(channel_id)

    async def get_channels(self, channel_ids: list[str]) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        unique_ids = list(dict.fromkeys(channel_id for channel_id in channel_ids if channel_id))
        for start in range(0, len(unique_ids), 50):
            chunk = unique_ids[start : start + 50]
            payload = await self._request_json(
                self.settings.youtube_data_api_base_url,
                "channels",
                params={
                    "part": "snippet,statistics,contentDetails,brandingSettings",
                    "id": ",".join(chunk),
                    "maxResults": len(chunk),
                },
                namespace="channels.list",
            )
            items = payload.get("items") if isinstance(payload.get("items"), list) else []
            result.extend(item for item in items if isinstance(item, dict))
        return result

    async def channel_videos(self, channel: dict[str, Any], max_videos: int) -> list[dict[str, Any]]:
        content = channel.get("contentDetails") if isinstance(channel.get("contentDetails"), dict) else {}
        playlists = content.get("relatedPlaylists") if isinstance(content.get("relatedPlaylists"), dict) else {}
        uploads = str(playlists.get("uploads") or "")
        if not uploads:
            return []
        playlist_items = await self._paginate(
            "playlistItems",
            params={"part": "contentDetails", "playlistId": uploads},
            namespace="playlistItems.uploads",
            max_items=max_videos,
        )
        video_ids = [
            str(item.get("contentDetails", {}).get("videoId") or "")
            for item in playlist_items
            if isinstance(item.get("contentDetails"), dict)
        ]
        return await self.get_videos([video_id for video_id in video_ids if video_id])

    async def search_videos(
        self,
        query: str,
        *,
        max_videos: int,
        language: str | None = None,
        region: str | None = None,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"part": "snippet", "type": "video", "q": query, "order": "relevance"}
        if language:
            params["relevanceLanguage"] = language
        if region:
            params["regionCode"] = region.upper()
        search = await self._paginate("search", params=params, namespace="search.videos", max_items=max_videos, quota_cost=100)
        ids = []
        for item in search:
            raw_id = item.get("id")
            if isinstance(raw_id, dict) and raw_id.get("videoId"):
                ids.append(str(raw_id["videoId"]))
        return await self.get_videos(ids)

    async def trending_videos(self, region: str, max_videos: int = 20) -> list[dict[str, Any]]:
        payload = await self._request_json(
            self.settings.youtube_data_api_base_url,
            "videos",
            params={
                "part": "snippet,statistics,contentDetails",
                "chart": "mostPopular",
                "regionCode": region.upper(),
                "maxResults": min(50, max_videos),
            },
            namespace="videos.trending",
        )
        items = payload.get("items") if isinstance(payload.get("items"), list) else []
        return [item for item in items if isinstance(item, dict)][:max_videos]

    async def comments(self, video_id: str, max_comments: int) -> list[dict[str, Any]]:
        return await self._paginate(
            "commentThreads",
            params={"part": "snippet", "videoId": video_id, "textFormat": "plainText", "order": "relevance"},
            namespace="comments.list",
            max_items=max_comments,
        )

    async def captions(self, video_id: str) -> list[dict[str, Any]]:
        payload = await self._request_json(
            self.settings.youtube_data_api_base_url,
            "captions",
            params={"part": "snippet", "videoId": video_id},
            namespace="captions.list",
            quota_cost=50,
            require_oauth=True,
        )
        items = payload.get("items") if isinstance(payload.get("items"), list) else []
        return [item for item in items if isinstance(item, dict)]

    async def download_caption(self, caption_id: str) -> str:
        return await self._request_text(
            f"captions/{caption_id}",
            params={"tfmt": "srt"},
            namespace="captions.download",
        )

    async def analytics_report(
        self,
        *,
        start_date: date,
        end_date: date,
        metrics: list[str],
        video_id: str | None = None,
        dimensions: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {
            "ids": "channel==MINE",
            "startDate": start_date.isoformat(),
            "endDate": end_date.isoformat(),
            "metrics": ",".join(metrics),
        }
        if video_id:
            params["filters"] = f"video=={video_id}"
        if dimensions:
            params["dimensions"] = ",".join(dimensions)
        payload = await self._request_json(
            self.settings.youtube_analytics_api_base_url,
            "reports",
            params=params,
            namespace="analytics.reports",
            require_oauth=True,
            private_cache=True,
        )
        headers = payload.get("columnHeaders") if isinstance(payload.get("columnHeaders"), list) else []
        names = [str(header.get("name") or "") for header in headers if isinstance(header, dict)]
        rows = payload.get("rows") if isinstance(payload.get("rows"), list) else []
        return [dict(zip(names, row, strict=False)) for row in rows if isinstance(row, list)]
