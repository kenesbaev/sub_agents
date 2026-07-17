from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
import sys
import tempfile
import time
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlencode, urlparse
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException
from starlette.requests import Request

ROOT = Path(__file__).resolve().parents[1]
TEST_DB_ROOT = tempfile.TemporaryDirectory()
os.environ["DATABASE_URL"] = f"sqlite:///{Path(TEST_DB_ROOT.name) / 'connected-apps-test.sqlite3'}"
sys.path.insert(0, str(ROOT / "backend"))

from app.config import get_settings  # noqa: E402
from app.connected_apps.router import (  # noqa: E402
    GenericOAuthConfig,
    OAuthConnectRequest,
    build_generic_oauth_url,
    connect_manual_secret_account,
    connect_oauth_provider,
    exchange_generic_oauth_code,
    exchange_refresh_token,
    fetch_generic_userinfo,
    generic_account_identity,
    generic_oauth_config,
    is_official_zapier_catch_hook_url,
    linkedin_oauth_scopes,
    meta_oauth_scopes,
    normalize_shopify_shop_domain,
    refresh_config_for_provider,
    safe_token_metadata,
    shopify_shop_domain_for_account,
    shopify_oauth_is_configured,
    validate_shopify_callback,
    verify_manual_secret,
)
from app.models import User  # noqa: E402
from app.connected_apps.service import integration_connection_state, sanitize_metadata  # noqa: E402


class FakeResponse:
    status_code = 200
    content = b'{"access_token":"access-token","refresh_token":"refresh-token","expires_in":3600}'

    def json(self) -> dict[str, object]:
        return {
            "access_token": "access-token",
            "refresh_token": "refresh-token",
            "expires_in": 3600,
        }


class CapturingAsyncClient:
    calls: list[dict[str, object]] = []

    def __init__(self, *_args: object, **_kwargs: object) -> None:
        pass

    async def __aenter__(self) -> "CapturingAsyncClient":
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    async def post(self, url: str, **kwargs: object) -> FakeResponse:
        self.calls.append({"url": url, **kwargs})
        return FakeResponse()


class SlackErrorResponse:
    status_code = 200
    content = b'{"ok":false,"error":"bad_client_secret"}'

    def json(self) -> dict[str, object]:
        return {"ok": False, "error": "bad_client_secret"}


class SlackErrorAsyncClient(CapturingAsyncClient):
    async def post(self, url: str, **kwargs: object) -> SlackErrorResponse:
        self.calls.append({"url": url, **kwargs})
        return SlackErrorResponse()


class EmptyIdentityResponse:
    status_code = 200
    content = b"{}"

    def json(self) -> dict[str, object]:
        return {}


class EmptyIdentityAsyncClient(CapturingAsyncClient):
    async def get(self, url: str, **kwargs: object) -> EmptyIdentityResponse:
        self.calls.append({"url": url, **kwargs})
        return EmptyIdentityResponse()


class ModelListResponse:
    status_code = 200
    content = b'{"data":[]}'

    def json(self) -> dict[str, object]:
        return {"data": []}


class CredentialVerificationAsyncClient(CapturingAsyncClient):
    async def get(self, url: str, **kwargs: object) -> ModelListResponse:
        self.calls.append({"url": url, **kwargs})
        return ModelListResponse()


class ConnectedAppsOAuthTest(unittest.TestCase):
    def test_token_metadata_is_recursively_redacted(self) -> None:
        metadata = safe_token_metadata(
            {
                "access_token": "top-level-secret",
                "expires_in": 3600,
                "profile": {
                    "name": "Ada",
                    "refresh_token": "nested-secret",
                    "credentials": {"api_key": "deep-secret"},
                    "incoming_webhook": {
                        "url": "https://hooks.slack.com/services/T000/B000/SECRET",
                    },
                },
            }
        )

        self.assertEqual(3600, metadata["expires_in"])
        self.assertEqual("Ada", metadata["profile"]["name"])
        self.assertNotIn("access_token", metadata)
        self.assertNotIn("refresh_token", metadata["profile"])
        self.assertNotIn("credentials", metadata["profile"])
        self.assertNotIn("incoming_webhook", metadata["profile"])

        legacy_response_metadata = sanitize_metadata(
            {
                "source": "generic_oauth",
                "provider_details": {
                    "name": "Legacy Slack connection",
                    "delivery_webhook": {"url": "https://hooks.slack.com/services/legacy-secret"},
                    "response_url": "https://hooks.slack.com/actions/legacy-secret",
                },
            }
        )
        self.assertEqual(
            {"source": "generic_oauth", "provider_details": {"name": "Legacy Slack connection"}},
            legacy_response_metadata,
        )

    provider_env = {
        "BACKEND_URL": "https://api.example.com",
        "SHOPIFY_CLIENT_ID": "shopify-client-id",
        "SHOPIFY_CLIENT_SECRET": "shopify-client-secret",
        "SHOPIFY_SHOP_DOMAIN": "sample-store.myshopify.com",
        "SHOPIFY_REDIRECT_URI": "https://api.example.com/api/connected-apps/shopify/callback",
        "TIKTOK_CLIENT_KEY": "tiktok-client-key",
        "TIKTOK_CLIENT_SECRET": "tiktok-client-secret",
        "TIKTOK_REDIRECT_URI": "https://api.example.com/api/connected-apps/tiktok/callback",
        "X_CLIENT_ID": "x-client-id",
        "X_CLIENT_SECRET": "x-client-secret",
        "X_REDIRECT_URI": "https://api.example.com/api/connected-apps/x/callback",
        "DISCORD_CLIENT_ID": "discord-client-id",
        "DISCORD_CLIENT_SECRET": "discord-client-secret",
        "DISCORD_REDIRECT_URI": "https://api.example.com/api/connected-apps/discord/callback",
        "LINKEDIN_CLIENT_ID": "linkedin-client-id",
        "LINKEDIN_CLIENT_SECRET": "linkedin-client-secret",
        "LINKEDIN_REDIRECT_URI": "https://api.example.com/api/connected-apps/linkedin/callback",
        "SLACK_CLIENT_ID": "slack-client-id",
        "SLACK_CLIENT_SECRET": "slack-client-secret",
        "SLACK_REDIRECT_URI": "https://api.example.com/api/connected-apps/slack/callback",
        "NOTION_CLIENT_ID": "notion-client-id",
        "NOTION_CLIENT_SECRET": "notion-client-secret",
        "NOTION_REDIRECT_URI": "https://api.example.com/api/connected-apps/notion/callback",
        "GITHUB_CLIENT_ID": "github-client-id",
        "GITHUB_CLIENT_SECRET": "github-client-secret",
        "GITHUB_REDIRECT_URI": "https://api.example.com/api/connected-apps/github/callback",
        "DROPBOX_CLIENT_ID": "dropbox-client-id",
        "DROPBOX_CLIENT_SECRET": "dropbox-client-secret",
        "DROPBOX_REDIRECT_URI": "https://api.example.com/api/connected-apps/dropbox/callback",
        "ONEDRIVE_CLIENT_ID": "onedrive-client-id",
        "ONEDRIVE_CLIENT_SECRET": "onedrive-client-secret",
        "ONEDRIVE_REDIRECT_URI": "https://api.example.com/api/connected-apps/onedrive/callback",
        "STRIPE_CLIENT_ID": "ca_stripe-client-id",
        "STRIPE_CLIENT_SECRET": "sk_test_stripe-secret",
        "STRIPE_REDIRECT_URI": "https://api.example.com/api/connected-apps/stripe/callback",
    }

    def setUp(self) -> None:
        self.environment = patch.dict(os.environ, self.provider_env, clear=False)
        self.environment.start()
        get_settings.cache_clear()
        CapturingAsyncClient.calls = []

    def tearDown(self) -> None:
        self.environment.stop()
        get_settings.cache_clear()

    def test_provider_urls_use_the_required_scope_format_and_x_pkce(self) -> None:
        shopify_url = build_generic_oauth_url(generic_oauth_config("shopify"), state="shopify:1:state")
        shopify_query = parse_qs(urlparse(shopify_url).query)
        self.assertEqual(
            "read_products,write_products,read_orders,read_customers,read_inventory,write_inventory,read_discounts,write_discounts,read_analytics",
            shopify_query["scope"][0],
        )
        self.assertEqual("https://sample-store.myshopify.com/admin/oauth/authorize", shopify_url.split("?", 1)[0])

        tiktok_url = build_generic_oauth_url(generic_oauth_config("tiktok"), state="tiktok:1:state")
        tiktok_query = parse_qs(urlparse(tiktok_url).query)
        self.assertEqual("tiktok-client-key", tiktok_query["client_key"][0])
        self.assertEqual("user.info.basic,video.list", tiktok_query["scope"][0])

        verifier = "test-pkce-verifier"
        x_url = build_generic_oauth_url(generic_oauth_config("x"), state="x:1:state", code_verifier=verifier)
        x_query = parse_qs(urlparse(x_url).query)
        expected_challenge = __import__("base64").urlsafe_b64encode(
            hashlib.sha256(verifier.encode("ascii")).digest()
        ).rstrip(b"=").decode("ascii")
        self.assertEqual("users.read tweet.read tweet.write offline.access", x_query["scope"][0])
        self.assertEqual("S256", x_query["code_challenge_method"][0])
        self.assertEqual(expected_challenge, x_query["code_challenge"][0])

        slack_url = build_generic_oauth_url(generic_oauth_config("slack"), state="slack:1:state")
        slack_query = parse_qs(urlparse(slack_url).query)
        self.assertEqual("channels:read,chat:write,users:read", slack_query["scope"][0])

    def test_x_token_and_refresh_exchange_use_basic_auth(self) -> None:
        config = GenericOAuthConfig(
            provider_key="x",
            auth_uri="https://x.com/i/oauth2/authorize",
            token_uri="https://api.x.com/2/oauth2/token",
            client_id="x-client-id",
            client_secret="x-client-secret",
            redirect_uri="https://api.example.com/api/connected-apps/x/callback",
            scopes=("users.read", "offline.access"),
            account_type="x_account",
            token_auth="basic",
        )
        with patch("app.connected_apps.router.httpx.AsyncClient", CapturingAsyncClient):
            token_data = asyncio.run(exchange_generic_oauth_code(config, "authorization-code", code_verifier="verifier"))
            refresh_data = asyncio.run(exchange_refresh_token(config, "refresh-token"))

        self.assertEqual("access-token", token_data["access_token"])
        self.assertEqual("access-token", refresh_data["access_token"])
        code_request, refresh_request = CapturingAsyncClient.calls
        self.assertEqual(("x-client-id", "x-client-secret"), code_request["auth"])
        self.assertEqual(("x-client-id", "x-client-secret"), refresh_request["auth"])
        self.assertEqual(
            {
                "code": "authorization-code",
                "grant_type": "authorization_code",
                "redirect_uri": "https://api.example.com/api/connected-apps/x/callback",
                "code_verifier": "verifier",
            },
            code_request["data"],
        )
        self.assertEqual({"grant_type": "refresh_token", "refresh_token": "refresh-token"}, refresh_request["data"])

    def test_production_generic_oauth_rejects_unsafe_endpoint_and_callback_overrides(self) -> None:
        production_settings = SimpleNamespace(is_production=True, backend_url="https://api.example.com")
        with patch("app.connected_apps.router.get_settings", return_value=production_settings):
            for provider_key in (
                "shopify",
                "tiktok",
                "x",
                "discord",
                "slack",
                "notion",
                "github",
                "dropbox",
                "onedrive",
                "stripe",
            ):
                with self.subTest(valid_provider=provider_key):
                    self.assertEqual(provider_key, generic_oauth_config(provider_key).provider_key)

            invalid_overrides = (
                {"GITHUB_TOKEN_URI": "http://github.com/login/oauth/access_token"},
                {"GITHUB_TOKEN_URI": "https://attacker.example/oauth/token"},
                {"GITHUB_USERINFO_URI": "https://attacker.example/user"},
                {"GITHUB_REDIRECT_URI": "https://attacker.example/api/connected-apps/github/callback"},
                {"GITHUB_REDIRECT_URI": "https://api.example.com/api/connected-apps/x/callback"},
            )
            for override in invalid_overrides:
                with self.subTest(override=override), patch.dict(os.environ, override, clear=False):
                    with self.assertRaises(HTTPException) as raised:
                        generic_oauth_config("github")
                    self.assertEqual(500, raised.exception.status_code)

    def test_notion_code_and_refresh_use_basic_auth_json_and_version_header(self) -> None:
        config = generic_oauth_config("notion")
        with patch("app.connected_apps.router.httpx.AsyncClient", CapturingAsyncClient):
            asyncio.run(exchange_generic_oauth_code(config, "authorization-code"))
            asyncio.run(exchange_refresh_token(config, "refresh-token"))

        code_request, refresh_request = CapturingAsyncClient.calls
        self.assertEqual(("notion-client-id", "notion-client-secret"), code_request["auth"])
        self.assertEqual("application/json", code_request["headers"]["Content-Type"])
        self.assertEqual("2026-03-11", code_request["headers"]["Notion-Version"])
        self.assertNotIn("data", code_request)
        self.assertEqual(
            {
                "code": "authorization-code",
                "grant_type": "authorization_code",
                "redirect_uri": "https://api.example.com/api/connected-apps/notion/callback",
            },
            code_request["json"],
        )
        self.assertEqual(("notion-client-id", "notion-client-secret"), refresh_request["auth"])
        self.assertEqual(
            {"grant_type": "refresh_token", "refresh_token": "refresh-token"},
            refresh_request["json"],
        )

    def test_slack_uses_basic_auth_and_rejects_http_200_error_payload(self) -> None:
        config = generic_oauth_config("slack")
        with patch("app.connected_apps.router.httpx.AsyncClient", CapturingAsyncClient):
            asyncio.run(exchange_generic_oauth_code(config, "authorization-code"))
        request = CapturingAsyncClient.calls[0]
        self.assertEqual(("slack-client-id", "slack-client-secret"), request["auth"])
        self.assertNotIn("client_id", request["data"])
        self.assertNotIn("client_secret", request["data"])

        CapturingAsyncClient.calls = []
        with (
            patch("app.connected_apps.router.httpx.AsyncClient", SlackErrorAsyncClient),
            self.assertRaises(HTTPException) as raised,
        ):
            asyncio.run(exchange_generic_oauth_code(config, "authorization-code"))
        self.assertEqual(400, raised.exception.status_code)

    def test_stripe_code_and_refresh_use_exact_secret_basic_contract(self) -> None:
        config = generic_oauth_config("stripe")
        with patch("app.connected_apps.router.httpx.AsyncClient", CapturingAsyncClient):
            asyncio.run(exchange_generic_oauth_code(config, "authorization-code"))
            asyncio.run(exchange_refresh_token(config, "refresh-token"))

        code_request, refresh_request = CapturingAsyncClient.calls
        self.assertEqual(("sk_test_stripe-secret", ""), code_request["auth"])
        self.assertEqual(
            {"code": "authorization-code", "grant_type": "authorization_code"},
            code_request["data"],
        )
        self.assertEqual(("sk_test_stripe-secret", ""), refresh_request["auth"])
        self.assertEqual(
            {"grant_type": "refresh_token", "refresh_token": "refresh-token"},
            refresh_request["data"],
        )

    def test_shopify_code_exchange_uses_expiring_offline_token_parameters(self) -> None:
        config = generic_oauth_config("shopify")
        with patch("app.connected_apps.router.httpx.AsyncClient", CapturingAsyncClient):
            asyncio.run(exchange_generic_oauth_code(config, "authorization-code"))

        request = CapturingAsyncClient.calls[0]
        self.assertEqual("https://sample-store.myshopify.com/admin/oauth/access_token", request["url"])
        self.assertEqual(
            {
                "code": "authorization-code",
                "expiring": "1",
                "client_id": "shopify-client-id",
                "client_secret": "shopify-client-secret",
            },
            request["data"],
        )

    def test_shopify_uses_the_merchant_selected_store_without_exposing_oauth_configuration(self) -> None:
        with patch.dict(os.environ, {"SHOPIFY_SHOP_DOMAIN": ""}, clear=False):
            get_settings.cache_clear()
            config = generic_oauth_config("shopify", shop_domain="other-store.myshopify.com")
            url = build_generic_oauth_url(config, state="shopify:1:state")
            self.assertEqual("https://other-store.myshopify.com/admin/oauth/authorize", url.split("?", 1)[0])
            self.assertTrue(shopify_oauth_is_configured())

        with self.assertRaises(HTTPException) as raised:
            generic_oauth_config("shopify", shop_domain="https://evil.example.com")
        self.assertEqual(400, raised.exception.status_code)

    def test_dynamic_shopify_domain_is_retained_for_account_identity_and_refresh(self) -> None:
        config = generic_oauth_config("shopify", shop_domain="other-store.myshopify.com")
        account_identifier, account_label = generic_account_identity(
            config,
            token_data={},
            userinfo={},
            fallback_email="merchant@example.com",
        )
        stored_account = SimpleNamespace(
            account_identifier="fallback-store.myshopify.com",
            metadata_json={"shopDomain": account_identifier},
        )
        refresh_config = refresh_config_for_provider(
            "shopify",
            shop_domain=shopify_shop_domain_for_account(stored_account),
        )

        self.assertEqual("other-store.myshopify.com", account_identifier)
        self.assertEqual("other-store.myshopify.com", account_label)
        self.assertEqual("other-store.myshopify.com", shopify_shop_domain_for_account(stored_account))
        self.assertIsNotNone(refresh_config)
        self.assertEqual("https://other-store.myshopify.com/admin/oauth/access_token", refresh_config.token_uri)

    def test_shopify_configuration_accepts_the_same_environment_aliases_as_the_oauth_flow(self) -> None:
        with patch.dict(
            os.environ,
            {
                "SHOPIFY_CLIENT_ID": "",
                "SHOPIFY_CLIENT_SECRET": "",
                "SHOPIFY_APP_ID": "shopify-app-id",
                "SHOPIFY_APP_SECRET": "shopify-app-secret",
            },
            clear=False,
        ):
            get_settings.cache_clear()
            self.assertTrue(shopify_oauth_is_configured())

    def test_shopify_callback_rejects_duplicate_hmac_parameters(self) -> None:
        config = generic_oauth_config("shopify")
        parameters = [
            ("code", "authorization-code"),
            ("shop", "sample-store.myshopify.com"),
            ("state", "shopify:1:state"),
            ("timestamp", str(int(time.time()))),
        ]
        signature = hmac.new(
            b"shopify-client-secret",
            urlencode(sorted(parameters)).encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        duplicate_hmac_request = Request(
            {
                "type": "http",
                "method": "GET",
                "path": "/api/connected-apps/shopify/callback",
                "headers": [],
                "query_string": urlencode([*parameters, ("hmac", signature), ("hmac", signature)]).encode("utf-8"),
            }
        )
        with self.assertRaises(HTTPException) as raised:
            validate_shopify_callback(
                duplicate_hmac_request,
                config,
                expected_shop_domain="sample-store.myshopify.com",
            )
        self.assertEqual(400, raised.exception.status_code)

    def test_shopify_connect_binds_the_selected_store_to_the_oauth_session_cookie(self) -> None:
        user = User(id=7, email="merchant@example.com")
        db = MagicMock()
        payload = OAuthConnectRequest.model_validate({"shopDomain": "other-store.myshopify.com"})
        with (
            patch(
                "app.connected_apps.router.oauth_authorization_url",
                return_value=("https://other-store.myshopify.com/admin/oauth/authorize", "shopify:7:nonce", None, "other-store.myshopify.com"),
            ) as authorization_url,
            patch("app.connected_apps.router.mark_oauth_connection_status"),
        ):
            response = connect_oauth_provider("shopify", payload, user, db)

        self.assertEqual(
            {"authorizationUrl": "https://other-store.myshopify.com/admin/oauth/authorize"},
            json.loads(response.body),
        )
        self.assertEqual("other-store.myshopify.com", authorization_url.call_args.kwargs["shop_domain"])
        cookies = "\n".join(response.headers.getlist("set-cookie"))
        self.assertIn("rebly_integration_shopify_shop=other-store.myshopify.com", cookies)

    def test_shopify_callback_requires_a_current_valid_hmac_for_the_configured_shop(self) -> None:
        config = generic_oauth_config("shopify")
        parameters = [
            ("code", "authorization-code"),
            ("host", "admin.shopify.com/store/sample-store"),
            ("shop", "sample-store.myshopify.com"),
            ("state", "shopify:1:state"),
            ("timestamp", str(int(time.time()))),
        ]
        signature = hmac.new(
            b"shopify-client-secret",
            urlencode(sorted(parameters)).encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        valid_request = Request(
            {
                "type": "http",
                "method": "GET",
                "path": "/api/connected-apps/shopify/callback",
                "headers": [],
                "query_string": urlencode([*parameters, ("hmac", signature)]).encode("utf-8"),
            }
        )
        validate_shopify_callback(valid_request, config, expected_shop_domain="sample-store.myshopify.com")

        tampered_request = Request(
            {
                "type": "http",
                "method": "GET",
                "path": "/api/connected-apps/shopify/callback",
                "headers": [],
                "query_string": urlencode([*parameters, ("hmac", "not-valid")]).encode("utf-8"),
            }
        )
        with self.assertRaises(HTTPException) as raised:
            validate_shopify_callback(tampered_request, config, expected_shop_domain="sample-store.myshopify.com")
        self.assertEqual(400, raised.exception.status_code)

        with self.assertRaises(HTTPException) as raised:
            validate_shopify_callback(valid_request, config, expected_shop_domain="other-store.myshopify.com")
        self.assertEqual(400, raised.exception.status_code)
        self.assertEqual("", normalize_shopify_shop_domain("https://evil.example.com"))

    def test_linkedin_uses_a_safe_default_and_an_explicit_scope_override(self) -> None:
        self.assertEqual(("openid", "profile", "email", "w_member_social"), linkedin_oauth_scopes())
        with patch.dict(os.environ, {"LINKEDIN_SCOPES": "openid,profile,email,w_member_social,r_member_social"}, clear=False):
            get_settings.cache_clear()
            self.assertEqual(
                ("openid", "profile", "email", "w_member_social", "r_member_social"),
                linkedin_oauth_scopes(),
            )

    def test_instagram_oauth_includes_basic_identity_permission(self) -> None:
        scopes = meta_oauth_scopes("instagram")
        self.assertIn("instagram_basic", scopes)
        self.assertIn("instagram_content_publish", scopes)

    def test_generic_userinfo_requires_a_verified_provider_identity(self) -> None:
        config = generic_oauth_config("github")
        with (
            patch("app.connected_apps.router.httpx.AsyncClient", EmptyIdentityAsyncClient),
            self.assertRaises(HTTPException) as raised,
        ):
            asyncio.run(fetch_generic_userinfo(config, "access-token"))
        self.assertEqual(400, raised.exception.status_code)
        self.assertNotIn("access-token", str(raised.exception.detail))

    def test_openai_and_claude_credentials_are_verified_without_exposing_them(self) -> None:
        with patch("app.connected_apps.router.httpx.AsyncClient", CredentialVerificationAsyncClient):
            asyncio.run(verify_manual_secret("openai", "openai-test-secret"))
            asyncio.run(verify_manual_secret("claude", "claude-test-secret"))

        openai_request, claude_request = CredentialVerificationAsyncClient.calls
        self.assertEqual("https://api.openai.com/v1/models", openai_request["url"])
        self.assertEqual("Bearer openai-test-secret", openai_request["headers"]["Authorization"])
        self.assertEqual("https://api.anthropic.com/v1/models", claude_request["url"])
        self.assertEqual("claude-test-secret", claude_request["headers"]["x-api-key"])
        self.assertEqual("2023-06-01", claude_request["headers"]["anthropic-version"])

    def test_zapier_accepts_only_official_catch_hook_urls_without_triggering_them(self) -> None:
        valid = "https://hooks.zapier.com/hooks/catch/123456/Abc_def-9/"
        for valid_url in (
            valid,
            "https://hooks.zapier.com/hooks/catch/123456/Abc_def-9/silent",
            "https://hooks.zapier.com/hooks/catch/123456/Abc_def-9/silent/",
        ):
            self.assertTrue(is_official_zapier_catch_hook_url(valid_url), valid_url)
        for invalid in (
            "http://hooks.zapier.com/hooks/catch/123456/abc/",
            "https://hooks.zapier.com.evil.example/hooks/catch/123456/abc/",
            "https://hooks.zapier.com:443/hooks/catch/123456/abc/",
            "https://hooks.zapier.com/hooks/catch/not-a-number/abc/",
            "https://hooks.zapier.com/hooks/catch/123456/abc/?token=secret",
            "https://hooks.zapier.com/hooks/catch/123456/abc/silent/extra",
        ):
            self.assertFalse(is_official_zapier_catch_hook_url(invalid), invalid)

        with patch("app.connected_apps.router.httpx.AsyncClient") as client:
            asyncio.run(verify_manual_secret("zapier", valid))
        client.assert_not_called()

    def test_failed_manual_credential_validation_never_stores_the_secret(self) -> None:
        user = User(id=7, email="owner@example.com")
        db = MagicMock()
        payload = SimpleNamespace(secret="invalid-secret", label=None, identifier=None)
        failure = HTTPException(status_code=400, detail="OpenAI rejected this credential.")
        with (
            patch("app.connected_apps.router.verify_manual_secret", new=AsyncMock(side_effect=failure)),
            patch("app.connected_apps.router.upsert_connected_account") as upsert,
            self.assertRaises(HTTPException),
        ):
            asyncio.run(connect_manual_secret_account("openai", payload, user, db))
        upsert.assert_not_called()
        db.commit.assert_not_called()

    def test_connection_state_calculation_does_not_mutate_database_models(self) -> None:
        stale = SimpleNamespace(
            status="connecting",
            updated_at=datetime.now(UTC) - timedelta(minutes=16),
            last_error=None,
        )
        self.assertEqual(("error", "Error", False), integration_connection_state(stale, []))
        self.assertEqual("connecting", stale.status)
        self.assertIsNone(stale.last_error)

        connected = SimpleNamespace(status="connected", updated_at=datetime.now(UTC), last_error=None)
        expired_token = SimpleNamespace(
            encrypted_access_token="encrypted-expired-token",
            expires_at=datetime.now(UTC) - timedelta(seconds=1),
            encrypted_refresh_token="encrypted-refresh-token",
        )
        self.assertEqual(
            ("reconnect_required", "Reconnect Required", False),
            integration_connection_state(connected, [expired_token]),
        )
        self.assertEqual("connected", connected.status)
        self.assertIsNone(connected.last_error)

    def test_connection_state_requires_a_usable_credential_and_tolerates_expired_secondary_accounts(self) -> None:
        connected = SimpleNamespace(status="connected", updated_at=datetime.now(UTC), last_error=None)
        self.assertEqual(
            ("reconnect_required", "Reconnect Required", False),
            integration_connection_state(connected, []),
        )

        missing_access_token = SimpleNamespace(
            encrypted_access_token=None,
            encrypted_refresh_token=None,
            expires_at=None,
        )
        self.assertEqual(
            ("reconnect_required", "Reconnect Required", False),
            integration_connection_state(connected, [missing_access_token]),
        )

        manual_secret = SimpleNamespace(
            encrypted_access_token="encrypted-manual-secret",
            encrypted_refresh_token=None,
            expires_at=None,
        )
        expired_secondary = SimpleNamespace(
            encrypted_access_token="encrypted-expired-token",
            encrypted_refresh_token="encrypted-refresh-token",
            expires_at=datetime.now(UTC) - timedelta(minutes=1),
        )
        self.assertEqual(
            ("connected", "Connected", True),
            integration_connection_state(connected, [manual_secret, expired_secondary]),
        )

        expired_without_refresh = SimpleNamespace(
            encrypted_access_token="encrypted-expired-token",
            encrypted_refresh_token=None,
            expires_at=datetime.now(UTC) - timedelta(minutes=1),
        )
        self.assertEqual(
            ("expired", "Expired", False),
            integration_connection_state(connected, [expired_without_refresh]),
        )


if __name__ == "__main__":
    unittest.main()
