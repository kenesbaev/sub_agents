from __future__ import annotations

import ipaddress
import socket
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx
from pydantic import BaseModel, Field, ValidationError, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.connected_apps.service import get_provider_record, get_user_integration, normalize_datetime
from app.models import IntegrationAccount, IntegrationToken
from app.token_crypto import decrypt_token

PROVIDER_KEY = "youtube"
CAPABILITIES = ("youtube.research", "youtube.analytics", "youtube.upload")
TOOLS = (
    "youtube_search_trends",
    "youtube_analyze_competitors",
    "youtube_analyze_video",
    "youtube_create_content_plan",
    "youtube_create_creative_package",
    "youtube_analyze_growth",
    "upload_youtube_video",
)

YOUTUBE_UPLOAD_SCOPE = "https://www.googleapis.com/auth/youtube.upload"
YOUTUBE_RESUMABLE_UPLOAD_URL = "https://www.googleapis.com/upload/youtube/v3/videos"
MAX_YOUTUBE_UPLOAD_BYTES = 512 * 1024 * 1024
MAX_REDIRECTS = 3
VIDEO_SUFFIXES = {".avi", ".m4v", ".mkv", ".mov", ".mp4", ".mpeg", ".mpg", ".webm"}


class YouTubePublishError(Exception):
    """A safe, user-facing YouTube publishing failure."""

    def __init__(self, detail: str, *, status_code: int = 400, reconnect_required: bool = False) -> None:
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code
        self.reconnect_required = reconnect_required


class YouTubeVideoPublishRequest(BaseModel):
    """Validated, server-side contract for the publish-capable YouTube agent tool."""

    media_url: str = Field(min_length=8, max_length=2048)
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=10_000)
    privacy_status: Literal["private", "unlisted", "public"] = "private"
    tags: list[str] = Field(default_factory=list, max_length=30)
    category_id: str = Field(default="22", min_length=1, max_length=3)
    made_for_kids: bool = False
    notify_subscribers: bool = True
    default_language: str | None = Field(default=None, max_length=16)
    account_id: int | None = Field(default=None, ge=1)
    source: str | None = Field(default=None, max_length=80)
    run_id: str | None = Field(default=None, max_length=80)

    @field_validator("media_url", "title", "description", "category_id", "default_language", "source", "run_id")
    @classmethod
    def strip_text_values(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip()

    @field_validator("title")
    @classmethod
    def validate_title(cls, value: str) -> str:
        if not value:
            raise ValueError("title is required")
        if _utf16_length(value) > 100:
            raise ValueError("title must be at most 100 characters")
        return value

    @field_validator("description")
    @classmethod
    def validate_description(cls, value: str) -> str:
        if _utf16_length(value) > 5000:
            raise ValueError("description must be at most 5000 characters")
        return value

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, tags: list[str]) -> list[str]:
        normalized: list[str] = []
        for tag in tags:
            cleaned = tag.strip()
            if not cleaned:
                continue
            if _utf16_length(cleaned) > 100:
                raise ValueError("each tag must be at most 100 characters")
            normalized.append(cleaned)
        if sum(_utf16_length(tag) + 1 for tag in normalized) > 500:
            raise ValueError("tags are too long for YouTube")
        return normalized

    @field_validator("category_id")
    @classmethod
    def validate_category_id(cls, value: str) -> str:
        if not value.isdigit():
            raise ValueError("category_id must be a numeric YouTube category ID")
        return value

    @field_validator("default_language")
    @classmethod
    def validate_default_language(cls, value: str | None) -> str | None:
        if value is None:
            return None
        parts = value.split("-", 1)
        if not (2 <= len(parts[0]) <= 3 and parts[0].isalpha()):
            raise ValueError("default_language must be a BCP-47 language code")
        if len(parts) == 2 and (not parts[1] or len(parts[1]) > 8 or not parts[1].isalnum()):
            raise ValueError("default_language must be a BCP-47 language code")
        return value

    @classmethod
    def from_tool_arguments(cls, arguments: dict[str, Any]) -> "YouTubeVideoPublishRequest":
        data = dict(arguments)
        aliases = {
            "media_url": ("mediaUrl",),
            "privacy_status": ("privacyStatus",),
            "category_id": ("categoryId",),
            "made_for_kids": ("madeForKids",),
            "notify_subscribers": ("notifySubscribers",),
            "default_language": ("defaultLanguage",),
            "account_id": ("accountId",),
            "run_id": ("runId",),
        }
        for canonical, alternate_names in aliases.items():
            if data.get(canonical) is not None:
                continue
            for alternate_name in alternate_names:
                if data.get(alternate_name) is not None:
                    data[canonical] = data[alternate_name]
                    break
        if data.get("description") is None:
            data["description"] = data.get("content") or data.get("text") or ""
        try:
            return cls.model_validate(data)
        except ValidationError as exc:
            errors = "; ".join(
                f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}" for error in exc.errors()
            )
            raise YouTubePublishError(f"Invalid YouTube upload request: {errors}") from exc


@dataclass(frozen=True)
class YouTubeUploadResult:
    video_id: str
    url: str
    privacy_status: str
    account_id: int
    account_identifier: str
    media_host: str
    media_size: int


@dataclass(frozen=True)
class DownloadedVideo:
    path: Path
    content_type: str
    size: int
    media_host: str

    def cleanup(self) -> None:
        self.path.unlink(missing_ok=True)


def _utf16_length(value: str) -> int:
    return len(value.encode("utf-16-le")) // 2


def _is_public_ip(value: str) -> bool:
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return False
    return address.is_global


def validate_public_video_url(value: str) -> str:
    """Allow only public HTTPS locations, including every later redirect target."""

    try:
        parsed = urlsplit(value.strip())
        port = parsed.port
    except ValueError as exc:
        raise YouTubePublishError("The video URL is invalid.") from exc
    host = (parsed.hostname or "").lower().rstrip(".")
    if parsed.scheme != "https" or not host or parsed.username or parsed.password:
        raise YouTubePublishError("Provide a public HTTPS video URL without credentials.")
    if port not in {None, 443}:
        raise YouTubePublishError("The video URL must use the standard HTTPS port.")
    if host == "localhost" or host.endswith(".local") or (
        _looks_like_ip(host) and not _is_public_ip(host)
    ):
        raise YouTubePublishError("The video URL must resolve to a public host.")
    if not _looks_like_ip(host):
        try:
            addresses = {entry[4][0] for entry in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)}
        except OSError as exc:
            raise YouTubePublishError("The video host could not be resolved.") from exc
        if not addresses or any(not _is_public_ip(address) for address in addresses):
            raise YouTubePublishError("The video URL must resolve to a public host.")
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path or "/", parsed.query, ""))


def _looks_like_ip(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return False
    return True


def _is_video_response(content_type: str, url: str) -> bool:
    normalized_type = content_type.split(";", 1)[0].strip().lower()
    if normalized_type.startswith("video/"):
        return True
    suffix = Path(urlsplit(url).path).suffix.lower()
    return normalized_type in {"application/octet-stream", "binary/octet-stream"} and suffix in VIDEO_SUFFIXES


def _content_length(response: httpx.Response) -> int | None:
    value = response.headers.get("content-length")
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def download_youtube_video_media(media_url: str) -> DownloadedVideo:
    current_url = validate_public_video_url(media_url)
    path: Path | None = None
    downloaded = False
    try:
        with httpx.Client(
            timeout=httpx.Timeout(connect=10.0, read=90.0, write=10.0, pool=10.0),
            follow_redirects=False,
        ) as client:
            for _ in range(MAX_REDIRECTS + 1):
                with client.stream("GET", current_url, headers={"Accept": "video/*"}) as response:
                    if response.status_code in {301, 302, 303, 307, 308}:
                        location = response.headers.get("location")
                        if not location:
                            raise YouTubePublishError("The video host returned an invalid redirect.", status_code=502)
                        current_url = validate_public_video_url(urljoin(current_url, location))
                        continue
                    if response.status_code >= 400:
                        raise YouTubePublishError("The video could not be downloaded from its public URL.", status_code=502)
                    content_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
                    if not _is_video_response(content_type, current_url):
                        raise YouTubePublishError("The media URL must return a supported video file.")
                    declared_size = _content_length(response)
                    if declared_size is not None and (declared_size <= 0 or declared_size > MAX_YOUTUBE_UPLOAD_BYTES):
                        raise YouTubePublishError("The video is too large to upload.")
                    with tempfile.NamedTemporaryFile(prefix="teamora-youtube-", suffix=".video", delete=False) as output:
                        path = Path(output.name)
                        size = 0
                        for chunk in response.iter_bytes():
                            if not chunk:
                                continue
                            size += len(chunk)
                            if size > MAX_YOUTUBE_UPLOAD_BYTES:
                                raise YouTubePublishError("The video is too large to upload.")
                            output.write(chunk)
                    if size <= 0:
                        raise YouTubePublishError("The video file is empty.")
                    result = DownloadedVideo(
                        path=path,
                        content_type=content_type or "application/octet-stream",
                        size=size,
                        media_host=urlsplit(current_url).hostname or "",
                    )
                    downloaded = True
                    return result
        raise YouTubePublishError("The video URL redirected too many times.", status_code=502)
    except YouTubePublishError:
        raise
    except (httpx.HTTPError, OSError) as exc:
        raise YouTubePublishError("The video could not be downloaded from its public URL.", status_code=502) from exc
    finally:
        if path is not None and not downloaded:
            path.unlink(missing_ok=True)


def _youtube_error_message(response: httpx.Response, fallback: str) -> str:
    try:
        payload = response.json() if response.content else {}
    except ValueError:
        payload = {}
    error = payload.get("error") if isinstance(payload, dict) else None
    reason = ""
    if isinstance(error, dict):
        errors = error.get("errors")
        if isinstance(errors, list) and errors and isinstance(errors[0], dict):
            reason = str(errors[0].get("reason") or "").lower()
    if reason in {"insufficientpermissions", "autherror", "invalidcredentials", "youtubesignuprequired"}:
        return "YouTube upload permission is missing. Reconnect YouTube and grant upload access."
    if reason in {"quotaexceeded", "dailylimitexceeded", "ratelimitexceeded", "userratelimitexceeded"}:
        return "YouTube upload is temporarily unavailable because the API quota was reached."
    return fallback


def _youtube_auth_failure(response: httpx.Response) -> bool:
    if response.status_code == 401:
        return True
    return "permission is missing" in _youtube_error_message(response, "").lower()


def _youtube_metadata(request: YouTubeVideoPublishRequest) -> dict[str, Any]:
    snippet: dict[str, Any] = {
        "title": request.title,
        "description": request.description,
        "categoryId": request.category_id,
    }
    if request.tags:
        snippet["tags"] = request.tags
    if request.default_language:
        snippet["defaultLanguage"] = request.default_language
    return {
        "snippet": snippet,
        "status": {
            "privacyStatus": request.privacy_status,
            "selfDeclaredMadeForKids": request.made_for_kids,
        },
    }


def _youtube_connection(
    db: Session,
    *,
    user_id: int,
    account_id: int | None,
) -> tuple[IntegrationAccount, str]:
    provider = get_provider_record(db, PROVIDER_KEY)
    integration = get_user_integration(db, user_id=user_id, provider_id=provider.id)
    if integration is None or integration.status != "connected":
        raise YouTubePublishError("Connect YouTube before uploading a video.", status_code=409)
    account_query = select(IntegrationAccount).where(
        IntegrationAccount.user_integration_id == integration.id,
        IntegrationAccount.provider_id == provider.id,
    )
    if account_id is not None:
        account_query = account_query.where(IntegrationAccount.id == account_id)
    else:
        account_query = account_query.order_by(IntegrationAccount.is_default.desc(), IntegrationAccount.created_at.asc())
    account = db.scalar(account_query)
    if account is None:
        raise YouTubePublishError("The selected YouTube channel is not available.", status_code=400)
    token = db.scalar(select(IntegrationToken).where(IntegrationToken.integration_account_id == account.id))
    if token is None or not token.encrypted_access_token:
        raise YouTubePublishError("YouTube authorization is incomplete. Reconnect YouTube.", status_code=409)
    expires_at = normalize_datetime(token.expires_at)
    if expires_at is not None and expires_at <= datetime.now(UTC):
        raise YouTubePublishError(
            "YouTube authorization expired. Reconnect YouTube and try again.",
            status_code=409,
            reconnect_required=True,
        )
    scopes = {scope for scope in (token.scopes or "").replace(",", " ").split() if scope}
    if YOUTUBE_UPLOAD_SCOPE not in scopes:
        raise YouTubePublishError(
            "YouTube upload permission is missing. Reconnect YouTube and grant upload access.",
            status_code=403,
            reconnect_required=True,
        )
    try:
        access_token = decrypt_token(token.encrypted_access_token)
    except Exception as exc:  # Token failures must never expose encrypted data.
        raise YouTubePublishError(
            "YouTube authorization could not be read. Reconnect YouTube.",
            status_code=409,
            reconnect_required=True,
        ) from exc
    if not access_token:
        raise YouTubePublishError("YouTube authorization is incomplete. Reconnect YouTube.", status_code=409)
    return account, access_token


def upload_video_to_youtube(
    access_token: str,
    video: DownloadedVideo,
    request: YouTubeVideoPublishRequest,
) -> tuple[str, str]:
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
        "Content-Type": "application/json; charset=UTF-8",
        "X-Upload-Content-Length": str(video.size),
        "X-Upload-Content-Type": video.content_type,
    }
    params = {
        "uploadType": "resumable",
        "part": "snippet,status",
        "notifySubscribers": str(request.notify_subscribers).lower(),
    }
    try:
        with httpx.Client(timeout=httpx.Timeout(connect=15.0, read=90.0, write=90.0, pool=15.0)) as client:
            session_response = client.post(
                YOUTUBE_RESUMABLE_UPLOAD_URL,
                params=params,
                headers=headers,
                json=_youtube_metadata(request),
            )
            if session_response.status_code >= 400:
                message = _youtube_error_message(session_response, "YouTube rejected the video metadata.")
                raise YouTubePublishError(
                    message,
                    status_code=409 if _youtube_auth_failure(session_response) else 400,
                    reconnect_required=_youtube_auth_failure(session_response),
                )
            upload_url = session_response.headers.get("location")
            if not upload_url:
                raise YouTubePublishError("YouTube did not create an upload session.", status_code=502)
            with video.path.open("rb") as content:
                upload_response = client.put(
                    upload_url,
                    headers={"Content-Type": video.content_type, "Content-Length": str(video.size)},
                    content=content,
                )
    except YouTubePublishError:
        raise
    except (OSError, httpx.HTTPError) as exc:
        raise YouTubePublishError("The video upload to YouTube failed. Try again.", status_code=502) from exc
    if upload_response.status_code >= 400:
        message = _youtube_error_message(upload_response, "YouTube rejected the video upload.")
        raise YouTubePublishError(
            message,
            status_code=409 if _youtube_auth_failure(upload_response) else 400,
            reconnect_required=_youtube_auth_failure(upload_response),
        )
    try:
        payload = upload_response.json() if upload_response.content else {}
    except ValueError as exc:
        raise YouTubePublishError("YouTube returned an invalid upload response.", status_code=502) from exc
    video_id = str(payload.get("id") or "") if isinstance(payload, dict) else ""
    if not video_id:
        raise YouTubePublishError("YouTube did not return a published video ID.", status_code=502)
    response_status = payload.get("status") if isinstance(payload, dict) else None
    privacy_status = (
        str(response_status.get("privacyStatus"))
        if isinstance(response_status, dict) and response_status.get("privacyStatus") in {"private", "unlisted", "public"}
        else request.privacy_status
    )
    return video_id, privacy_status


def publish_youtube_video(
    db: Session,
    *,
    user_id: int,
    arguments: dict[str, Any],
) -> tuple[YouTubeVideoPublishRequest, YouTubeUploadResult]:
    """Download a public video server-side and publish it with the user's encrypted YouTube token."""

    if arguments.get("approved") is not True:
        raise YouTubePublishError(
            "upload_youtube_video requires explicit approval before it can make an external change.",
            status_code=409,
        )
    request = YouTubeVideoPublishRequest.from_tool_arguments(arguments)
    account, access_token = _youtube_connection(db, user_id=user_id, account_id=request.account_id)
    video = download_youtube_video_media(request.media_url)
    try:
        video_id, privacy_status = upload_video_to_youtube(access_token, video, request)
    finally:
        video.cleanup()
    return request, YouTubeUploadResult(
        video_id=video_id,
        url=f"https://www.youtube.com/watch?v={video_id}",
        privacy_status=privacy_status,
        account_id=account.id,
        account_identifier=account.account_identifier,
        media_host=video.media_host,
        media_size=video.size,
    )
