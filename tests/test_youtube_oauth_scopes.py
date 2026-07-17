from __future__ import annotations

import os
import sys
import tempfile
import unittest
import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from unittest.mock import AsyncMock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from fastapi import HTTPException
from starlette.requests import Request


ROOT = Path(__file__).resolve().parents[1]
TEST_DB_ROOT = tempfile.TemporaryDirectory()
os.environ["DATABASE_URL"] = f"sqlite:///{Path(TEST_DB_ROOT.name) / 'youtube-oauth-scopes.sqlite3'}"
sys.path.insert(0, str(ROOT / "backend"))

from app.config import get_settings  # noqa: E402
from app.connected_apps.google_oauth import (  # noqa: E402
    google_connected_scopes,
    google_token_grants_provider,
    google_token_scopes,
)
from app.connected_apps.providers import (  # noqa: E402
    YOUTUBE_ANALYTICS_READ_SCOPE,
    YOUTUBE_DATA_READ_SCOPE,
    YOUTUBE_UPLOAD_SCOPE,
)
from app.connected_apps.router import (  # noqa: E402
    OAuthConnectRequest,
    oauth_authorization_url,
    refresh_due_oauth_tokens,
    validate_state,
)
from app.connected_apps.service import provider_status_payload, upsert_connected_account  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.models import IntegrationToken, User, UserIntegration  # noqa: E402
from app.token_crypto import decrypt_token  # noqa: E402


class YouTubeOAuthScopesTest(unittest.TestCase):
    def setUp(self) -> None:
        self.environment = patch.dict(
            os.environ,
            {
                "GOOGLE_CLIENT_ID": "client-id",
                "GOOGLE_CLIENT_SECRET": "client-secret",
                "GOOGLE_CONNECTED_REDIRECT_URI": "http://127.0.0.1:8000/api/connected-apps/google/callback",
            },
            clear=False,
        )
        self.environment.start()
        get_settings.cache_clear()

    def tearDown(self) -> None:
        self.environment.stop()
        get_settings.cache_clear()

    def test_growth_connection_is_read_only(self) -> None:
        scopes = set(google_connected_scopes("youtube"))

        self.assertIn(YOUTUBE_DATA_READ_SCOPE, scopes)
        self.assertIn(YOUTUBE_ANALYTICS_READ_SCOPE, scopes)
        self.assertNotIn(YOUTUBE_UPLOAD_SCOPE, scopes)
        self.assertTrue({"openid", "email", "profile"}.isdisjoint(scopes))

    def test_publisher_upgrade_is_explicit_and_includes_growth_scopes(self) -> None:
        scopes = set(google_connected_scopes("youtube", youtube_access="publisher"))

        self.assertTrue(
            {YOUTUBE_DATA_READ_SCOPE, YOUTUBE_ANALYTICS_READ_SCOPE, YOUTUBE_UPLOAD_SCOPE}
            .issubset(scopes)
        )

    def test_authorization_url_uses_requested_access_mode(self) -> None:
        user = User(id=11, email="creator@example.com")
        growth_url, *_ = oauth_authorization_url("youtube", user)
        publisher_url, *_ = oauth_authorization_url("youtube", user, youtube_access="publisher")

        growth_scopes = set(parse_qs(urlparse(growth_url).query)["scope"][0].split())
        publisher_scopes = set(parse_qs(urlparse(publisher_url).query)["scope"][0].split())
        self.assertNotIn(YOUTUBE_UPLOAD_SCOPE, growth_scopes)
        self.assertIn(YOUTUBE_UPLOAD_SCOPE, publisher_scopes)

    def test_connect_payload_rejects_unknown_youtube_access_mode(self) -> None:
        with self.assertRaises(ValueError):
            OAuthConnectRequest.model_validate({"youtubeAccess": "automatic-publish"})

    def test_missing_scope_response_is_never_inferred_as_granted(self) -> None:
        self.assertFalse(google_token_grants_provider({"access_token": "token"}, "youtube"))
        self.assertEqual("", google_token_scopes({"access_token": "token"}, "youtube"))

    def test_callback_rejects_wrong_oauth_state(self) -> None:
        request = Request(
            {
                "type": "http",
                "method": "GET",
                "path": "/api/connected-apps/youtube/callback",
                "headers": [(b"cookie", b"rebly_integration_oauth_state=youtube%3A11%3Aexpected")],
                "query_string": b"",
            }
        )
        with self.assertRaises(HTTPException) as raised:
            validate_state(request, "youtube:11:tampered")
        self.assertEqual(400, raised.exception.status_code)

    def test_status_reports_missing_capabilities_from_actual_granted_scopes(self) -> None:
        engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(bind=engine)
        try:
            with Session(engine) as db:
                user = User(email="scopes@example.com")
                db.add(user)
                db.flush()
                upsert_connected_account(
                    db,
                    user_id=user.id,
                    provider_key="youtube",
                    account_identifier="channel-1",
                    account_label="Channel",
                    account_type="youtube_channel",
                    access_token="access-token",
                    scopes=YOUTUBE_DATA_READ_SCOPE,
                )
                db.commit()

                payload = provider_status_payload(db, user)
                youtube = next(item for item in payload["providers"] if item["key"] == "youtube")
                capabilities = {item["key"]: item for item in youtube["capabilities"]}

                self.assertTrue(capabilities["youtube.research"]["granted"])
                self.assertFalse(capabilities["youtube.analytics"]["granted"])
                self.assertFalse(capabilities["youtube.upload"]["granted"])
                self.assertEqual("", capabilities["youtube.analytics"]["scope"])
        finally:
            Base.metadata.drop_all(bind=engine)

    def test_expired_youtube_access_token_is_refreshed_without_a_real_network_call(self) -> None:
        engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(bind=engine)
        try:
            with Session(engine) as db:
                user = User(email="refresh@example.com")
                db.add(user)
                db.flush()
                account = upsert_connected_account(
                    db,
                    user_id=user.id,
                    provider_key="youtube",
                    account_identifier="channel-refresh",
                    account_label="Refresh channel",
                    account_type="youtube_channel",
                    access_token="expired-access-token",
                    refresh_token="stored-refresh-token",
                    expires_at=datetime.now(UTC) - timedelta(minutes=1),
                    scopes=f"{YOUTUBE_DATA_READ_SCOPE} {YOUTUBE_ANALYTICS_READ_SCOPE}",
                )
                db.commit()

                refreshed = {
                    "access_token": "fresh-access-token",
                    "expires_in": 3600,
                    "token_type": "Bearer",
                    "scope": f"{YOUTUBE_DATA_READ_SCOPE} {YOUTUBE_ANALYTICS_READ_SCOPE}",
                }
                exchange = AsyncMock(return_value=refreshed)
                with patch("app.connected_apps.router.exchange_refresh_token", new=exchange):
                    asyncio.run(refresh_due_oauth_tokens(db, user))
                db.commit()

                token = db.query(IntegrationToken).filter_by(integration_account_id=account.id).one()
                integration = db.get(UserIntegration, token.user_integration_id)
                self.assertEqual("fresh-access-token", decrypt_token(token.encrypted_access_token))
                self.assertGreater(token.expires_at.replace(tzinfo=UTC), datetime.now(UTC))
                self.assertEqual("connected", integration.status)
                self.assertIsNone(integration.last_error)
                exchange.assert_awaited_once()
        finally:
            Base.metadata.drop_all(bind=engine)


if __name__ == "__main__":
    unittest.main()
