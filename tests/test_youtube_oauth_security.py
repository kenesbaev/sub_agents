from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from unittest.mock import AsyncMock, patch

import httpx
from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session


ROOT = Path(__file__).resolve().parents[1]
TEST_DB_ROOT = tempfile.TemporaryDirectory()
os.environ["DATABASE_URL"] = f"sqlite:///{Path(TEST_DB_ROOT.name) / 'youtube-oauth-security.sqlite3'}"
sys.path.insert(0, str(ROOT / "backend"))

from app.config import get_settings  # noqa: E402
from app.connected_apps.google_oauth import (  # noqa: E402
    exchange_google_code,
    store_google_oauth_accounts,
    youtube_channel_info,
)
from app.connected_apps.providers import (  # noqa: E402
    YOUTUBE_ANALYTICS_READ_SCOPE,
    YOUTUBE_DATA_READ_SCOPE,
    YOUTUBE_UPLOAD_SCOPE,
)
from app.connected_apps.router import (  # noqa: E402
    OAuthConnectRequest,
    connect_oauth_provider,
    oauth_error_redirect,
)
from app.connected_apps.service import (  # noqa: E402
    get_provider_record,
    get_user_integration,
    upsert_connected_account,
)
from app.db.base import Base  # noqa: E402
from app.models import IntegrationAccount, IntegrationToken, User  # noqa: E402


class StubAsyncClient:
    def __init__(
        self,
        *,
        post_response: httpx.Response | None = None,
        get_response: httpx.Response | None = None,
        post_error: Exception | None = None,
        get_error: Exception | None = None,
    ) -> None:
        self.post_response = post_response
        self.get_response = get_response
        self.post_error = post_error
        self.get_error = get_error

    async def __aenter__(self) -> "StubAsyncClient":
        return self

    async def __aexit__(self, exc_type: object, exc: object, traceback: object) -> None:
        return None

    async def post(self, *args: object, **kwargs: object) -> httpx.Response:
        if self.post_error is not None:
            raise self.post_error
        if self.post_response is None:
            raise AssertionError("Unexpected HTTP POST")
        return self.post_response

    async def get(self, *args: object, **kwargs: object) -> httpx.Response:
        if self.get_error is not None:
            raise self.get_error
        if self.get_response is None:
            raise AssertionError("Unexpected HTTP GET")
        return self.get_response


class YouTubeOAuthSecurityTest(unittest.TestCase):
    def setUp(self) -> None:
        self.environment = patch.dict(
            os.environ,
            {
                "GOOGLE_CLIENT_ID": "client-id",
                "GOOGLE_CLIENT_SECRET": "client-secret",
                "GOOGLE_CONNECTED_REDIRECT_URI": "http://127.0.0.1:8000/api/connected-apps/google/callback",
                "INTEGRATION_ENCRYPTION_SECRET": "test-only-integration-encryption-secret",
                "FRONTEND_URL": "http://127.0.0.1:3000",
            },
            clear=False,
        )
        self.environment.start()
        get_settings.cache_clear()
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(bind=self.engine)

    def tearDown(self) -> None:
        Base.metadata.drop_all(bind=self.engine)
        self.engine.dispose()
        self.environment.stop()
        get_settings.cache_clear()

    def test_publisher_upgrade_start_and_error_preserve_existing_connected_token(self) -> None:
        with Session(self.engine) as db:
            user = User(email="publisher-upgrade@example.com")
            db.add(user)
            db.flush()
            account = upsert_connected_account(
                db,
                user_id=user.id,
                provider_key="youtube",
                account_identifier="UCexistingchannel123",
                account_label="Existing channel",
                account_type="youtube_channel",
                access_token="existing-access-token",
                refresh_token="existing-refresh-token",
                scopes=f"{YOUTUBE_DATA_READ_SCOPE} {YOUTUBE_ANALYTICS_READ_SCOPE}",
            )
            db.commit()

            provider = get_provider_record(db, "youtube")
            integration = get_user_integration(db, user_id=user.id, provider_id=provider.id)
            self.assertIsNotNone(integration)
            token = db.scalar(select(IntegrationToken).where(IntegrationToken.integration_account_id == account.id))
            self.assertIsNotNone(token)
            encrypted_access_before = token.encrypted_access_token
            encrypted_refresh_before = token.encrypted_refresh_token

            response = connect_oauth_provider(
                "youtube",
                OAuthConnectRequest.model_validate({"youtubeAccess": "publisher"}),
                user=user,
                db=db,
            )
            authorization_url = json.loads(response.body)["authorizationUrl"]
            requested_scopes = set(parse_qs(urlparse(authorization_url).query)["scope"][0].split())
            self.assertIn(YOUTUBE_UPLOAD_SCOPE, requested_scopes)

            db.refresh(integration)
            db.refresh(token)
            self.assertEqual("connected", integration.status)
            self.assertEqual(encrypted_access_before, token.encrypted_access_token)
            self.assertEqual(encrypted_refresh_before, token.encrypted_refresh_token)

            oauth_error_redirect(
                db,
                user=user,
                provider_key="youtube",
                detail="Access was denied by the account owner",
            )

            db.refresh(integration)
            db.refresh(token)
            self.assertEqual("connected", integration.status)
            self.assertEqual(encrypted_access_before, token.encrypted_access_token)
            self.assertEqual(encrypted_refresh_before, token.encrypted_refresh_token)
            self.assertIn("denied", (integration.last_error or "").lower())

    def test_exchange_invalid_json_raises_safe_http_exception(self) -> None:
        stub = StubAsyncClient(post_response=httpx.Response(200, content=b"not-json: access-token-secret"))
        with patch("app.connected_apps.google_oauth.httpx.AsyncClient", return_value=stub):
            with self.assertRaises(HTTPException) as raised:
                asyncio.run(exchange_google_code(code="authorization-code-secret", redirect_uri="https://example.test/callback"))

        self.assertEqual(502, raised.exception.status_code)
        detail = str(raised.exception.detail)
        self.assertNotIn("access-token-secret", detail)
        self.assertNotIn("authorization-code-secret", detail)

    def test_exchange_timeout_raises_safe_http_exception(self) -> None:
        timeout = httpx.ReadTimeout(
            "provider timeout containing authorization-code-secret",
            request=httpx.Request("POST", "https://oauth2.googleapis.com/token"),
        )
        stub = StubAsyncClient(post_error=timeout)
        with patch("app.connected_apps.google_oauth.httpx.AsyncClient", return_value=stub):
            with self.assertRaises(HTTPException) as raised:
                asyncio.run(exchange_google_code(code="authorization-code-secret", redirect_uri="https://example.test/callback"))

        self.assertEqual(504, raised.exception.status_code)
        self.assertNotIn("authorization-code-secret", str(raised.exception.detail))

    def test_youtube_channel_info_rejects_missing_real_channel(self) -> None:
        response = httpx.Response(200, json={"items": []})
        stub = StubAsyncClient(get_response=response)
        with patch("app.connected_apps.google_oauth.httpx.AsyncClient", return_value=stub):
            with self.assertRaises(HTTPException) as raised:
                asyncio.run(
                    youtube_channel_info(
                        "youtube-access-token-secret",
                        {
                            "id": "fallback-google-identity",
                            "email": "fallback@example.com",
                            "name": "Fallback identity",
                        },
                    )
                )

        self.assertEqual(400, raised.exception.status_code)
        self.assertNotIn("fallback-google-identity", str(raised.exception.detail))
        self.assertNotIn("youtube-access-token-secret", str(raised.exception.detail))

    def test_storing_second_youtube_channel_switches_explicit_default(self) -> None:
        with Session(self.engine) as db:
            user = User(email="channel-switch@example.com")
            db.add(user)
            db.flush()
            first = upsert_connected_account(
                db,
                user_id=user.id,
                provider_key="youtube",
                account_identifier="UCfirstchannel1234",
                account_label="First channel",
                account_type="youtube_channel",
                access_token="first-access-token",
                refresh_token="first-refresh-token",
                scopes=YOUTUBE_DATA_READ_SCOPE,
            )
            db.commit()
            self.assertTrue(first.is_default)

            with (
                patch(
                    "app.connected_apps.google_oauth.google_userinfo",
                    new=AsyncMock(
                        return_value={
                            "id": "google-user-id",
                            "email": user.email,
                            "name": "Channel owner",
                        }
                    ),
                ),
                patch(
                    "app.connected_apps.google_oauth.youtube_channel_info",
                    new=AsyncMock(
                        return_value={
                            "id": "UCsecondchannel567",
                            "email": user.email,
                            "name": "Second channel",
                        }
                    ),
                ),
            ):
                accounts = asyncio.run(
                    store_google_oauth_accounts(
                        db,
                        user=user,
                        token_data={
                            "access_token": "second-access-token",
                            "refresh_token": "second-refresh-token",
                            "token_type": "Bearer",
                            "expires_in": 3600,
                            "scope": f"{YOUTUBE_DATA_READ_SCOPE} {YOUTUBE_ANALYTICS_READ_SCOPE}",
                        },
                        provider_keys=("youtube",),
                    )
                )
            db.commit()

            self.assertEqual(1, len(accounts))
            second = accounts[0]
            db.refresh(first)
            db.refresh(second)
            self.assertFalse(first.is_default)
            self.assertTrue(second.is_default)
            self.assertNotEqual(first.id, second.id)

            defaults = db.scalars(
                select(IntegrationAccount).where(
                    IntegrationAccount.user_integration_id == second.user_integration_id,
                    IntegrationAccount.is_default.is_(True),
                )
            ).all()
            self.assertEqual([second.id], [account.id for account in defaults])


if __name__ == "__main__":
    unittest.main()
