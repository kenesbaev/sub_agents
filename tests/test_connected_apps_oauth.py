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
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlencode, urlparse
from unittest.mock import MagicMock, patch

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
    connect_oauth_provider,
    exchange_generic_oauth_code,
    exchange_refresh_token,
    generic_account_identity,
    generic_oauth_config,
    linkedin_oauth_scopes,
    normalize_shopify_shop_domain,
    refresh_config_for_provider,
    safe_token_metadata,
    shopify_shop_domain_for_account,
    shopify_oauth_is_configured,
    validate_shopify_callback,
)
from app.models import User  # noqa: E402


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
                },
            }
        )

        self.assertEqual(3600, metadata["expires_in"])
        self.assertEqual("Ada", metadata["profile"]["name"])
        self.assertNotIn("access_token", metadata)
        self.assertNotIn("refresh_token", metadata["profile"])
        self.assertNotIn("credentials", metadata["profile"])

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


if __name__ == "__main__":
    unittest.main()
