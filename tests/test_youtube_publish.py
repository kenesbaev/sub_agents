from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[1]
TEST_DB_ROOT = tempfile.TemporaryDirectory()
os.environ["DATABASE_URL"] = f"sqlite:///{Path(TEST_DB_ROOT.name) / 'youtube-publish-test.sqlite3'}"
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "kaliya-core" / "src"))

from app.connected_apps.youtube_integration import (  # noqa: E402
    DownloadedVideo,
    YouTubePublishError,
    YouTubeUploadResult,
    YouTubeVideoPublishRequest,
    _youtube_connection,
    publish_youtube_video,
    upload_video_to_youtube,
    validate_public_video_url,
)
from app.connected_apps.router import AgentToolExecuteRequest, execute_agent_tool  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.models import IntegrationAccount, IntegrationProvider, IntegrationToken, User, UserIntegration  # noqa: E402
from kaliya.agent_tool_registry import can_agent_use_tool, tool_requires_approval  # noqa: E402


class FakeResponse:
    def __init__(
        self,
        *,
        status_code: int = 200,
        headers: dict[str, str] | None = None,
        payload: dict[str, object] | None = None,
    ) -> None:
        self.status_code = status_code
        self.headers = headers or {}
        self.payload = payload or {}
        self.content = b"{}"

    def json(self) -> dict[str, object]:
        return self.payload


class CapturingUploadClient:
    calls: list[dict[str, object]] = []

    def __init__(self, *_args: object, **_kwargs: object) -> None:
        pass

    def __enter__(self) -> "CapturingUploadClient":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def post(self, url: str, **kwargs: object) -> FakeResponse:
        self.calls.append({"method": "POST", "url": url, **kwargs})
        return FakeResponse(headers={"location": "https://upload.youtube.example/session"})

    def put(self, url: str, **kwargs: object) -> FakeResponse:
        body = kwargs.get("content")
        assert hasattr(body, "read")
        self.calls.append({"method": "PUT", "url": url, "body": body.read(), **kwargs})
        return FakeResponse(payload={"id": "video-123", "status": {"privacyStatus": "private"}})


class YouTubePublishTest(unittest.TestCase):
    def test_tool_request_accepts_camel_case_and_uses_text_as_description(self) -> None:
        request = YouTubeVideoPublishRequest.from_tool_arguments(
            {
                "mediaUrl": "https://media.example.test/launch.mp4",
                "title": " Product launch ",
                "text": " Video description ",
                "privacyStatus": "unlisted",
                "categoryId": "28",
                "madeForKids": False,
                "notifySubscribers": False,
                "accountId": 42,
                "tags": ["AI", " launch "],
            }
        )

        self.assertEqual("Product launch", request.title)
        self.assertEqual("Video description", request.description)
        self.assertEqual("unlisted", request.privacy_status)
        self.assertEqual("28", request.category_id)
        self.assertEqual(42, request.account_id)
        self.assertEqual(["AI", "launch"], request.tags)

    def test_private_or_non_https_video_urls_are_rejected_before_download(self) -> None:
        for url in ("http://cdn.example.test/video.mp4", "https://127.0.0.1/video.mp4", "https://localhost/video.mp4"):
            with self.subTest(url=url), self.assertRaises(YouTubePublishError):
                validate_public_video_url(url)

    def test_public_video_url_uses_resolved_public_address(self) -> None:
        resolved = [(None, None, None, None, ("93.184.216.34", 443))]
        with patch("app.connected_apps.youtube_integration.socket.getaddrinfo", return_value=resolved):
            normalized = validate_public_video_url("https://cdn.example.test/video.mp4#fragment")
        self.assertEqual("https://cdn.example.test/video.mp4", normalized)

    def test_resumable_upload_sends_metadata_then_binary(self) -> None:
        temporary = tempfile.NamedTemporaryFile(delete=False)
        temporary.write(b"video-bytes")
        temporary.close()
        video = DownloadedVideo(
            path=Path(temporary.name),
            content_type="video/mp4",
            size=len(b"video-bytes"),
            media_host="cdn.example.test",
        )
        request = YouTubeVideoPublishRequest(
            media_url="https://cdn.example.test/video.mp4",
            title="Launch",
            description="Ship it",
            privacy_status="public",
            tags=["launch"],
        )
        CapturingUploadClient.calls = []

        try:
            with patch("app.connected_apps.youtube_integration.httpx.Client", CapturingUploadClient):
                video_id, privacy_status = upload_video_to_youtube("token-never-log", video, request)
        finally:
            video.cleanup()

        self.assertEqual("video-123", video_id)
        self.assertEqual("private", privacy_status)
        initialize, binary_upload = CapturingUploadClient.calls
        self.assertEqual("POST", initialize["method"])
        self.assertEqual("resumable", initialize["params"]["uploadType"])
        self.assertEqual("Bearer token-never-log", initialize["headers"]["Authorization"])
        self.assertEqual("Launch", initialize["json"]["snippet"]["title"])
        self.assertEqual("public", initialize["json"]["status"]["privacyStatus"])
        self.assertEqual("PUT", binary_upload["method"])
        self.assertEqual(b"video-bytes", binary_upload["body"])
        self.assertEqual("video/mp4", binary_upload["headers"]["Content-Type"])

    def test_only_the_publisher_agent_receives_the_publish_capable_youtube_tool(self) -> None:
        self.assertTrue(can_agent_use_tool("dev", "upload_youtube_video"))
        self.assertFalse(can_agent_use_tool("scout", "upload_youtube_video"))
        self.assertTrue(tool_requires_approval("upload_youtube_video"))

    def test_publish_requires_explicit_approval_before_reading_tokens_or_downloading_media(self) -> None:
        with self.assertRaisesRegex(YouTubePublishError, "explicit approval"):
            publish_youtube_video(
                MagicMock(),
                user_id=4,
                arguments={
                    "mediaUrl": "https://media.example.test/launch.mp4",
                    "title": "Launch",
                },
            )

    def test_youtube_connection_uses_only_the_authenticated_users_encrypted_channel_token(self) -> None:
        engine = create_engine("sqlite://")
        Base.metadata.create_all(bind=engine)
        try:
            with Session(engine) as db:
                owner = User(email="owner@example.com")
                other_user = User(email="other@example.com")
                provider = IntegrationProvider(key="youtube", name="YouTube", auth_type="oauth2")
                db.add_all([owner, other_user, provider])
                db.flush()
                integration = UserIntegration(user_id=owner.id, provider_id=provider.id, status="connected")
                db.add(integration)
                db.flush()
                account = IntegrationAccount(
                    user_integration_id=integration.id,
                    provider_id=provider.id,
                    account_identifier="channel-123",
                    account_label="Owner channel",
                    account_type="youtube_channel",
                    is_default=True,
                )
                db.add(account)
                db.flush()
                db.add(
                    IntegrationToken(
                        user_integration_id=integration.id,
                        integration_account_id=account.id,
                        encrypted_access_token="ciphertext",
                        scopes="https://www.googleapis.com/auth/youtube.upload",
                    )
                )
                db.commit()

                with patch("app.connected_apps.youtube_integration.decrypt_token", return_value="decrypted-oauth-token") as decrypt:
                    loaded_account, access_token = _youtube_connection(db, user_id=owner.id, account_id=account.id)

                decrypt.assert_called_once_with("ciphertext")
                self.assertEqual(account.id, loaded_account.id)
                self.assertEqual("decrypted-oauth-token", access_token)
                with self.assertRaises(YouTubePublishError):
                    _youtube_connection(db, user_id=other_user.id, account_id=account.id)

                token = db.query(IntegrationToken).filter_by(integration_account_id=account.id).one()
                token.scopes = ""
                db.commit()
                with self.assertRaisesRegex(YouTubePublishError, "upload permission is missing"):
                    _youtube_connection(db, user_id=owner.id, account_id=account.id)
        finally:
            Base.metadata.drop_all(bind=engine)

    def test_agent_tools_dispatches_an_approved_youtube_upload_and_records_safe_activity(self) -> None:
        db = MagicMock()
        user = SimpleNamespace(id=4)
        arguments = {
            "mediaUrl": "https://media.example.test/launch.mp4",
            "title": "Launch",
            "approved": True,
            "agent": "dev",
            "runId": "run-42",
            "taskId": 91,
        }
        request = YouTubeVideoPublishRequest.from_tool_arguments(arguments)
        upload = YouTubeUploadResult(
            video_id="video-123",
            url="https://www.youtube.com/watch?v=video-123",
            privacy_status="unlisted",
            account_id=17,
            account_identifier="channel-123",
            media_host="media.example.test",
            media_size=1234,
        )

        with (
            patch("app.connected_apps.router.refresh_due_oauth_tokens", new=AsyncMock()) as refresh,
            patch("app.connected_apps.router.publish_youtube_video", return_value=(request, upload)) as publish,
            patch("app.connected_apps.router.write_activity") as write_activity,
            patch("app.connected_apps.router.update_publish_task_from_results") as update_task,
        ):
            response = asyncio.run(
                execute_agent_tool(
                    AgentToolExecuteRequest(tool="upload_youtube_video", arguments=arguments),
                    user=user,
                    db=db,
                )
            )

        refresh.assert_awaited_once_with(db, user)
        publish.assert_called_once_with(db, user_id=4, arguments=arguments)
        write_activity.assert_called_once()
        activity = write_activity.call_args.kwargs
        self.assertEqual("youtube", activity["service"])
        self.assertEqual("upload_video", activity["action"])
        self.assertEqual("published", activity["status"])
        self.assertEqual("video-123", activity["external_id"])
        self.assertEqual(17, activity["metadata_json"]["accountId"])
        self.assertEqual(91, activity["metadata_json"]["taskId"])
        self.assertNotIn("access_token", activity["metadata_json"])
        task_update = update_task.call_args.kwargs
        self.assertEqual(91, task_update["task_id"])
        self.assertEqual("run-42", task_update["run_id"])
        self.assertTrue(task_update["results"][0].ok)
        self.assertEqual("video-123", task_update["results"][0].external_id)
        self.assertEqual("https://www.youtube.com/watch?v=video-123", task_update["results"][0].url)
        self.assertEqual(
            {
                "ok": True,
                "result": {
                    "platform": "youtube",
                    "videoId": "video-123",
                    "url": "https://www.youtube.com/watch?v=video-123",
                    "privacyStatus": "unlisted",
                    "accountId": 17,
                },
            },
            response,
        )
        db.commit.assert_called_once()

    def test_agent_tools_marks_youtube_reconnect_failures_without_exposing_tokens(self) -> None:
        db = MagicMock()
        user = SimpleNamespace(id=4)
        failure = YouTubePublishError(
            "YouTube upload permission is missing. Reconnect YouTube and grant upload access.",
            status_code=403,
            reconnect_required=True,
        )
        arguments = {"approved": True, "accountId": 17, "runId": "run-42", "taskId": 91}

        with (
            patch("app.connected_apps.router.refresh_due_oauth_tokens", new=AsyncMock()),
            patch("app.connected_apps.router.publish_youtube_video", side_effect=failure),
            patch("app.connected_apps.router.set_user_integration_status") as set_status,
            patch("app.connected_apps.router.write_activity") as write_activity,
            patch("app.connected_apps.router.update_publish_task_from_results") as update_task,
        ):
            with self.assertRaises(HTTPException) as raised:
                asyncio.run(
                    execute_agent_tool(
                        AgentToolExecuteRequest(tool="upload_youtube_video", arguments=arguments),
                        user=user,
                        db=db,
                    )
                )

        self.assertEqual(403, raised.exception.status_code)
        self.assertNotIn("token", str(raised.exception.detail).lower())
        set_status.assert_called_once_with(
            db,
            user_id=4,
            provider_key="youtube",
            status="reconnect_required",
            last_error=failure.detail,
        )
        write_activity.assert_called_once()
        activity = write_activity.call_args.kwargs
        self.assertEqual("failed", activity["status"])
        self.assertEqual({"tool": "upload_youtube_video", "accountId": 17, "runId": "run-42", "taskId": 91}, activity["metadata_json"])
        task_update = update_task.call_args.kwargs
        self.assertEqual(91, task_update["task_id"])
        self.assertFalse(task_update["results"][0].ok)
        self.assertIn("upload permission", task_update["results"][0].error)
        db.commit.assert_called_once()


if __name__ == "__main__":
    unittest.main()
