from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import os
import re
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from urllib.parse import urlencode, urlparse
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.connected_apps.google_oauth import (
    YouTubeAccessMode,
    exchange_google_code,
    google_connected_scopes,
    store_google_oauth_accounts,
)
from app.connected_apps.google_actions import (
    GOOGLE_WRITE_AGENT_TOOLS,
    execute_google_agent_tool,
    is_google_agent_tool,
)
from app.connected_apps.providers import OAuthUrlBuilder, PROVIDERS
from app.connected_apps.youtube_integration import YouTubePublishError, publish_youtube_video
from app.connected_apps.service import (
    create_scheduled_post,
    disconnect_provider,
    get_provider_record,
    get_user_integration,
    list_activity,
    list_scheduled_posts,
    provider_status_payload,
    sanitize_metadata,
    set_user_integration_status,
    upsert_connected_account,
    write_activity,
)
from app.db.session import get_db
from app.integrations import (
    connected_account_credentials,
    default_connected_account_id,
    find_publish_task,
    update_publish_task_from_results,
)
from app.models import (
    IntegrationAccount,
    IntegrationProvider,
    IntegrationToken,
    InstagramIntegration,
    TelegramBotIntegration,
    User,
    UserIntegration,
)
from app.security import get_current_user
from app.schemas import PublishTargetResult
from app.token_crypto import decrypt_token, encrypt_token

router = APIRouter(tags=["connected-apps"])

INTEGRATION_STATE_COOKIE = "rebly_integration_oauth_state"
INTEGRATION_PKCE_COOKIE = "rebly_integration_pkce_verifier"
INTEGRATION_SHOPIFY_SHOP_COOKIE = "rebly_integration_shopify_shop"
PUBLIC_OAUTH_SETUP_ERROR = "This integration is not available yet. Please contact your workspace admin."


class TelegramAccountConnectRequest(BaseModel):
    bot_token: str = Field(min_length=9, max_length=256)
    target_chat_id: str = Field(min_length=1, max_length=255)
    label: str | None = Field(default=None, max_length=255)
    account_type: Literal["channel", "group", "bot"] = "channel"


class ManualSecretAccountConnectRequest(BaseModel):
    secret: str = Field(min_length=6, max_length=4096)
    label: str | None = Field(default=None, max_length=255)
    identifier: str | None = Field(default=None, max_length=255)


class OAuthConnectRequest(BaseModel):
    # A store domain is account data, not OAuth client configuration. It lets a
    # merchant connect their own shop without exposing administrator credentials.
    shop_domain: str | None = Field(default=None, alias="shopDomain", min_length=1, max_length=255)
    youtube_access: YouTubeAccessMode = Field(default="growth", alias="youtubeAccess")


class ScheduledPostCreateRequest(BaseModel):
    platform: Literal["telegram", "instagram"]
    content: str = Field(min_length=1, max_length=4096)
    publish_at: datetime
    timezone: str = Field(default="UTC", max_length=80)
    repeat_rule: str | None = Field(default=None, max_length=160)
    media_url: str | None = Field(default=None, max_length=2048)
    media_type: str | None = Field(default=None, max_length=120)
    account_id: int | None = None
    source: str | None = Field(default=None, max_length=80)
    run_id: str | None = Field(default=None, max_length=80)


SCHEDULED_DELIVERY_PLATFORMS = frozenset({"telegram", "instagram"})


def validate_scheduler_fields(
    *,
    platform: str,
    publish_at: datetime,
    repeat_rule: str | None,
    media_url: str | None,
    timezone_name: str = "UTC",
) -> datetime:
    if platform not in SCHEDULED_DELIVERY_PLATFORMS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Scheduled publishing currently supports only Telegram and Instagram.",
        )
    if repeat_rule:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Recurring scheduled publishing is not available yet.",
        )
    try:
        ZoneInfo(timezone_name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="timezone must be a valid IANA timezone name.",
        ) from exc
    if publish_at.tzinfo is None or publish_at.utcoffset() is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="publish_at must include a UTC offset or Z suffix.",
        )
    if platform == "instagram":
        parsed = urlparse((media_url or "").strip())
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Scheduled Instagram publishing requires a public HTTPS media URL.",
            )
    return publish_at.astimezone(UTC)


class ActivityWriteRequest(BaseModel):
    agent: str | None = Field(default=None, max_length=120)
    service: str = Field(min_length=1, max_length=80)
    action: str = Field(min_length=1, max_length=160)
    status: str = Field(min_length=1, max_length=40)
    external_id: str | None = Field(default=None, max_length=255)
    error: str | None = Field(default=None, max_length=500)
    metadata: dict[str, Any] | None = None


class AgentToolExecuteRequest(BaseModel):
    tool: str = Field(min_length=1, max_length=120)
    arguments: dict[str, Any] = Field(default_factory=dict)


@dataclass(frozen=True)
class GenericOAuthConfig:
    provider_key: str
    auth_uri: str
    token_uri: str
    client_id: str
    client_secret: str
    redirect_uri: str
    scopes: tuple[str, ...]
    account_type: str
    userinfo_uri: str | None = None
    client_id_param: str = "client_id"
    token_auth: str = "body"
    token_body_format: str = "form"
    token_headers: dict[str, str] | None = None
    extra_params: dict[str, str] | None = None
    scope_delimiter: str = " "
    authorization_code_extra_params: dict[str, str] | None = None
    include_authorization_code_grant_type: bool = True
    include_redirect_uri_in_token_exchange: bool = True
    # Shopify OAuth endpoints are store-specific. Keep the selected store on the
    # server-side config so token/account operations cannot fall back to a
    # different default shop from the environment.
    shop_domain: str | None = None


GENERIC_OAUTH_DEFAULTS: dict[str, dict[str, Any]] = {
    "shopify": {
        "auth_uri": "",
        "token_uri": "",
        "account_type": "shopify_store",
        "userinfo_uri": "",
        "scope_delimiter": ",",
        "authorization_code_extra_params": {"expiring": "1"},
        "include_authorization_code_grant_type": False,
        "include_redirect_uri_in_token_exchange": False,
    },
    "tiktok": {
        "auth_uri": "https://www.tiktok.com/v2/auth/authorize/",
        "token_uri": "https://open.tiktokapis.com/v2/oauth/token/",
        "client_id_param": "client_key",
        "account_type": "tiktok_account",
        "userinfo_uri": "https://open.tiktokapis.com/v2/user/info/",
        "scope_delimiter": ",",
    },
    "x": {
        "auth_uri": "https://x.com/i/oauth2/authorize",
        "token_uri": "https://api.x.com/2/oauth2/token",
        "account_type": "x_account",
        "userinfo_uri": "https://api.x.com/2/users/me?user.fields=username,name",
        "token_auth": "basic",
    },
    "discord": {
        "auth_uri": "https://discord.com/oauth2/authorize",
        "token_uri": "https://discord.com/api/oauth2/token",
        "account_type": "discord_user",
        "userinfo_uri": "https://discord.com/api/users/@me",
    },
    "slack": {
        "auth_uri": "https://slack.com/oauth/v2/authorize",
        "token_uri": "https://slack.com/api/oauth.v2.access",
        "account_type": "slack_workspace",
        "token_auth": "basic",
        "scope_delimiter": ",",
    },
    "notion": {
        "auth_uri": "https://api.notion.com/v1/oauth/authorize",
        "token_uri": "https://api.notion.com/v1/oauth/token",
        "account_type": "notion_workspace",
        "token_auth": "basic",
        "token_body_format": "json",
        "token_headers": {"Notion-Version": "2026-03-11"},
        "extra_params": {"owner": "user"},
    },
    "github": {
        "auth_uri": "https://github.com/login/oauth/authorize",
        "token_uri": "https://github.com/login/oauth/access_token",
        "account_type": "github_user",
        "userinfo_uri": "https://api.github.com/user",
    },
    "dropbox": {
        "auth_uri": "https://www.dropbox.com/oauth2/authorize",
        "token_uri": "https://api.dropboxapi.com/oauth2/token",
        "account_type": "dropbox_account",
        "userinfo_uri": "https://api.dropboxapi.com/2/users/get_current_account",
        "extra_params": {"token_access_type": "offline"},
    },
    "onedrive": {
        "auth_uri": "https://login.microsoftonline.com/common/oauth2/v2.0/authorize",
        "token_uri": "https://login.microsoftonline.com/common/oauth2/v2.0/token",
        "account_type": "microsoft_account",
        "userinfo_uri": "https://graph.microsoft.com/v1.0/me",
    },
    "stripe": {
        "auth_uri": "https://connect.stripe.com/oauth/authorize",
        "token_uri": "https://connect.stripe.com/oauth/token",
        "account_type": "stripe_account",
        "token_auth": "secret_basic",
        "include_redirect_uri_in_token_exchange": False,
    },
}

GENERIC_OAUTH_ENDPOINT_HOSTS: dict[str, dict[str, frozenset[str]]] = {
    "tiktok": {
        "auth_uri": frozenset({"www.tiktok.com"}),
        "token_uri": frozenset({"open.tiktokapis.com"}),
        "userinfo_uri": frozenset({"open.tiktokapis.com"}),
    },
    "x": {
        "auth_uri": frozenset({"x.com"}),
        "token_uri": frozenset({"api.x.com"}),
        "userinfo_uri": frozenset({"api.x.com"}),
    },
    "discord": {
        "auth_uri": frozenset({"discord.com"}),
        "token_uri": frozenset({"discord.com"}),
        "userinfo_uri": frozenset({"discord.com"}),
    },
    "slack": {
        "auth_uri": frozenset({"slack.com", "slack-gov.com"}),
        "token_uri": frozenset({"slack.com", "slack-gov.com"}),
    },
    "notion": {
        "auth_uri": frozenset({"api.notion.com"}),
        "token_uri": frozenset({"api.notion.com"}),
    },
    "github": {
        "auth_uri": frozenset({"github.com"}),
        "token_uri": frozenset({"github.com"}),
        "userinfo_uri": frozenset({"api.github.com"}),
    },
    "dropbox": {
        "auth_uri": frozenset({"dropbox.com", "www.dropbox.com"}),
        "token_uri": frozenset({"api.dropboxapi.com"}),
        "userinfo_uri": frozenset({"api.dropboxapi.com"}),
    },
    "onedrive": {
        "auth_uri": frozenset(
            {"login.microsoftonline.com", "login.microsoftonline.us", "login.partner.microsoftonline.cn"}
        ),
        "token_uri": frozenset(
            {"login.microsoftonline.com", "login.microsoftonline.us", "login.partner.microsoftonline.cn"}
        ),
        "userinfo_uri": frozenset(
            {"graph.microsoft.com", "graph.microsoft.us", "microsoftgraph.chinacloudapi.cn"}
        ),
    },
    "stripe": {
        "auth_uri": frozenset({"connect.stripe.com"}),
        "token_uri": frozenset({"connect.stripe.com"}),
    },
}

MANUAL_SECRET_PROVIDER_KEYS = {"openai", "claude", "zapier"}
ZAPIER_CATCH_HOOK_PATH_PATTERN = re.compile(r"^/hooks/catch/[1-9]\d*/[A-Za-z0-9_-]+(?:/silent)?/?$")
REQUIRED_OAUTH_SCOPES: dict[str, tuple[str, ...]] = {
    "x": ("offline.access",),
}
HTTPS_REDIRECT_PROVIDER_KEYS = {"linkedin", "tiktok"}
SHOPIFY_SHOP_DOMAIN_PATTERN = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.myshopify\.com$")
SHOPIFY_API_VERSION_PATTERN = re.compile(r"^\d{4}-\d{2}$")


def oauth_endpoint_is_safe_for_production(
    value: str,
    *,
    allowed_hosts: frozenset[str],
    allow_query: bool = False,
) -> bool:
    try:
        parsed = urlparse(value)
        port = parsed.port
    except ValueError:
        return False
    return bool(
        parsed.scheme == "https"
        and parsed.hostname in allowed_hosts
        and port in {None, 443}
        and parsed.username is None
        and parsed.password is None
        and not parsed.params
        and not parsed.fragment
        and bool(parsed.path and parsed.path.startswith("/"))
        and (allow_query or not parsed.query)
    )


def generic_oauth_callback_is_safe_for_production(config: GenericOAuthConfig) -> bool:
    settings = get_settings()
    try:
        backend = urlparse(str(settings.backend_url))
        callback = urlparse(config.redirect_uri)
        backend_port = backend.port or 443
        callback_port = callback.port or 443
    except ValueError:
        return False
    return bool(
        backend.scheme == "https"
        and callback.scheme == "https"
        and callback.hostname == backend.hostname
        and callback_port == backend_port
        and callback.username is None
        and callback.password is None
        and not callback.params
        and not callback.query
        and not callback.fragment
        and callback.path == f"/api/connected-apps/{config.provider_key}/callback"
    )


def validate_generic_oauth_production_endpoints(config: GenericOAuthConfig) -> None:
    settings = get_settings()
    if not settings.is_production:
        return

    if config.provider_key == "shopify":
        allowed_by_endpoint = {
            "auth_uri": frozenset({config.shop_domain or ""}),
            "token_uri": frozenset({config.shop_domain or ""}),
            "userinfo_uri": frozenset({config.shop_domain or ""}),
        }
    else:
        allowed_by_endpoint = GENERIC_OAUTH_ENDPOINT_HOSTS.get(config.provider_key, {})

    endpoints = {
        "auth_uri": config.auth_uri,
        "token_uri": config.token_uri,
        "userinfo_uri": config.userinfo_uri,
    }
    valid = generic_oauth_callback_is_safe_for_production(config)
    for endpoint_name, endpoint in endpoints.items():
        if not endpoint:
            continue
        allowed_hosts = allowed_by_endpoint.get(endpoint_name, frozenset())
        valid = valid and oauth_endpoint_is_safe_for_production(
            endpoint,
            allowed_hosts=allowed_hosts,
            allow_query=endpoint_name == "userinfo_uri",
        )
    if not valid:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=PUBLIC_OAUTH_SETUP_ERROR)


def oauth_redirect(provider_key: str) -> str:
    settings = get_settings()
    if provider_key in {"google", "youtube"}:
        return settings.google_connected_redirect_uri
    if provider_key in {"instagram", "facebook"}:
        return settings.meta_redirect_uri
    if provider_key == "linkedin":
        return settings.linkedin_redirect_uri
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown provider")


def generic_oauth_redirect(provider_key: str) -> str:
    return f"{str(get_settings().backend_url).rstrip('/')}/api/connected-apps/{provider_key}/callback"


def oauth_redirect_uri_is_valid(provider_key: str, redirect_uri: str) -> bool:
    if provider_key not in HTTPS_REDIRECT_PROVIDER_KEYS:
        return bool(redirect_uri)
    parsed = urlparse(redirect_uri)
    return parsed.scheme == "https" and bool(parsed.netloc)


def provider_env_value(provider_key: str, *names: str, default: str = "") -> str:
    prefix = provider_key.upper().replace("-", "_")
    settings = get_settings()
    for name in names:
        env_name = name if name.startswith(f"{prefix}_") else f"{prefix}_{name}"
        settings_name = env_name.lower()
        value = str(getattr(settings, settings_name, "") or "").strip()
        if not value:
            value = (os.environ.get(env_name) or "").strip()
        if value:
            return value
    return default


def parse_scopes(value: str) -> tuple[str, ...]:
    return tuple(scope for scope in value.replace(",", " ").split() if scope)


def provider_scopes(provider_key: str) -> tuple[str, ...]:
    configured = provider_env_value(provider_key, "SCOPES")
    default_scopes = tuple(
        scope
        for capability_scope in PROVIDERS[provider_key].scopes
        for scope in parse_scopes(capability_scope)
    )
    configured_scopes = parse_scopes(configured) if configured else default_scopes
    return tuple(dict.fromkeys((*configured_scopes, *REQUIRED_OAUTH_SCOPES.get(provider_key, ()))))


def normalize_shopify_shop_domain(value: str) -> str:
    domain = value.strip().lower()
    if domain.startswith("https://"):
        domain = domain.removeprefix("https://")
    elif domain.startswith("http://"):
        domain = domain.removeprefix("http://")
    domain = domain.strip().strip("/")
    if domain and "." not in domain:
        domain = f"{domain}.myshopify.com"
    return domain if SHOPIFY_SHOP_DOMAIN_PATTERN.fullmatch(domain) else ""


def shopify_store_domain(shop_domain: str | None = None) -> str:
    raw_domain = (
        shop_domain
        if shop_domain is not None and shop_domain.strip()
        else provider_env_value("shopify", "SHOP_DOMAIN", "STORE_DOMAIN", "SHOPIFY_SHOP_DOMAIN")
    )
    return normalize_shopify_shop_domain(raw_domain)


def shopify_oauth_is_configured() -> bool:
    redirect_uri = provider_env_value("shopify", "REDIRECT_URI", default=generic_oauth_redirect("shopify"))
    api_version = provider_env_value("shopify", "API_VERSION", default="2026-07")
    return bool(
        provider_env_value("shopify", "CLIENT_ID", "APP_ID", "CLIENT_KEY")
        and provider_env_value("shopify", "CLIENT_SECRET", "APP_SECRET", "SECRET")
        and redirect_uri
        and SHOPIFY_API_VERSION_PATTERN.fullmatch(api_version)
    )


def generic_oauth_config(provider_key: str, *, shop_domain: str | None = None) -> GenericOAuthConfig:
    if provider_key not in GENERIC_OAUTH_DEFAULTS or provider_key not in PROVIDERS:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown OAuth provider")

    defaults = GENERIC_OAUTH_DEFAULTS[provider_key]
    client_id = provider_env_value(provider_key, "CLIENT_ID", "APP_ID", "CLIENT_KEY")
    client_secret = provider_env_value(provider_key, "CLIENT_SECRET", "APP_SECRET", "SECRET")
    redirect_uri = provider_env_value(provider_key, "REDIRECT_URI", default=generic_oauth_redirect(provider_key))
    auth_uri = provider_env_value(provider_key, "AUTH_URI", default=str(defaults.get("auth_uri") or ""))
    token_uri = provider_env_value(provider_key, "TOKEN_URI", default=str(defaults.get("token_uri") or ""))
    userinfo_uri = provider_env_value(provider_key, "USERINFO_URI", default=str(defaults.get("userinfo_uri") or ""))

    if not oauth_redirect_uri_is_valid(provider_key, redirect_uri):
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=PUBLIC_OAUTH_SETUP_ERROR)

    effective_shop_domain: str | None = None
    if provider_key == "shopify":
        requested_shop_domain = shop_domain.strip() if shop_domain else ""
        effective_shop_domain = shopify_store_domain(requested_shop_domain or None)
        if requested_shop_domain and not effective_shop_domain:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Enter a valid Shopify .myshopify.com store domain.",
            )
        if not effective_shop_domain:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=PUBLIC_OAUTH_SETUP_ERROR,
            )
        auth_uri = auth_uri or f"https://{effective_shop_domain}/admin/oauth/authorize"
        token_uri = token_uri or f"https://{effective_shop_domain}/admin/oauth/access_token"
        api_version = provider_env_value("shopify", "API_VERSION", default="2026-07")
        if not SHOPIFY_API_VERSION_PATTERN.fullmatch(api_version):
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=PUBLIC_OAUTH_SETUP_ERROR)
        userinfo_uri = userinfo_uri or f"https://{effective_shop_domain}/admin/api/{api_version}/shop.json"

    if not client_id or not client_secret or not auth_uri or not token_uri:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=PUBLIC_OAUTH_SETUP_ERROR,
        )

    config = GenericOAuthConfig(
        provider_key=provider_key,
        auth_uri=auth_uri,
        token_uri=token_uri,
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri=redirect_uri,
        scopes=provider_scopes(provider_key),
        account_type=str(defaults.get("account_type") or f"{provider_key}_account"),
        userinfo_uri=userinfo_uri or None,
        client_id_param=str(defaults.get("client_id_param") or "client_id"),
        token_auth=str(defaults.get("token_auth") or "body"),
        token_body_format=str(defaults.get("token_body_format") or "form"),
        token_headers=dict(defaults.get("token_headers") or {}),
        extra_params=dict(defaults.get("extra_params") or {}),
        scope_delimiter=str(defaults.get("scope_delimiter") or " "),
        authorization_code_extra_params=dict(defaults.get("authorization_code_extra_params") or {}),
        include_authorization_code_grant_type=bool(defaults.get("include_authorization_code_grant_type", True)),
        include_redirect_uri_in_token_exchange=bool(defaults.get("include_redirect_uri_in_token_exchange", True)),
        shop_domain=effective_shop_domain,
    )
    validate_generic_oauth_production_endpoints(config)
    return config


def build_generic_oauth_url(config: GenericOAuthConfig, *, state: str, code_verifier: str | None = None) -> str:
    params = {
        config.client_id_param: config.client_id,
        "redirect_uri": config.redirect_uri,
        "response_type": "code",
        "state": state,
    }
    if config.scopes:
        params["scope"] = config.scope_delimiter.join(config.scopes)
    if config.extra_params:
        params.update(config.extra_params)
    if config.provider_key == "x":
        verifier = code_verifier or secrets.token_urlsafe(48)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).rstrip(b"=").decode("ascii")
        params["code_challenge"] = challenge
        params["code_challenge_method"] = "S256"
    return f"{config.auth_uri}?{urlencode(params)}"


def set_state_cookie(response: Response, state: str) -> None:
    settings = get_settings()
    response.set_cookie(
        INTEGRATION_STATE_COOKIE,
        state,
        max_age=10 * 60,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )


def set_pkce_cookie(response: Response, code_verifier: str | None) -> None:
    if not code_verifier:
        return
    settings = get_settings()
    response.set_cookie(
        INTEGRATION_PKCE_COOKIE,
        code_verifier,
        max_age=10 * 60,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )


def set_shopify_shop_cookie(response: Response, shop_domain: str | None) -> None:
    if not shop_domain:
        return
    settings = get_settings()
    response.set_cookie(
        INTEGRATION_SHOPIFY_SHOP_COOKIE,
        shop_domain,
        max_age=10 * 60,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )


def validate_state(request: Request, state: str) -> None:
    expected_state = request.cookies.get(INTEGRATION_STATE_COOKIE)
    if not expected_state or not hmac.compare_digest(expected_state, state):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid OAuth state")


def validate_shopify_callback(
    request: Request,
    config: GenericOAuthConfig,
    *,
    expected_shop_domain: str | None = None,
) -> None:
    received_hmac_values = request.query_params.getlist("hmac")
    received_hmac = received_hmac_values[0] if len(received_hmac_values) == 1 else ""
    callback_shop = normalize_shopify_shop_domain(request.query_params.get("shop") or "")
    timestamp = request.query_params.get("timestamp") or ""
    if not received_hmac or not callback_shop or not timestamp:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid Shopify callback")

    try:
        callback_timestamp = int(timestamp)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid Shopify callback") from exc
    if abs(int(datetime.now(UTC).timestamp()) - callback_timestamp) > 10 * 60:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Expired Shopify callback")

    expected_shop = normalize_shopify_shop_domain(expected_shop_domain or "")
    if not expected_shop or callback_shop != expected_shop:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid Shopify callback")

    signed_pairs = sorted((key, value) for key, value in request.query_params.multi_items() if key != "hmac")
    message = urlencode(signed_pairs)
    expected_hmac = hmac.new(
        config.client_secret.encode("utf-8"),
        message.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(expected_hmac, received_hmac):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid Shopify callback")


def finish_redirect(response: RedirectResponse) -> RedirectResponse:
    response.delete_cookie(INTEGRATION_STATE_COOKIE, path="/", samesite="lax")
    response.delete_cookie(INTEGRATION_PKCE_COOKIE, path="/", samesite="lax")
    response.delete_cookie(INTEGRATION_SHOPIFY_SHOP_COOKIE, path="/", samesite="lax")
    return response


def dashboard_redirect(tab: str = "connected") -> str:
    return f"{str(get_settings().frontend_url).rstrip('/')}/dashboard?view=settings&tab={tab}"


def oauth_error_message(provider_key: str, detail: object | None = None) -> str:
    provider_name = PROVIDERS.get(provider_key).name if provider_key in PROVIDERS else "This app"
    message = str(detail or "").strip()
    if message == PUBLIC_OAUTH_SETUP_ERROR:
        return message
    technical_terms = (
        "client",
        "configured",
        "exchange",
        "json",
        "oauth",
        "redirect",
        "scope",
        "secret",
        "token",
        "uri",
        "url",
    )
    if message and not any(term in message.lower() for term in technical_terms):
        return message[:500]
    return f"{provider_name} connection could not be completed. Please try again."


def mark_oauth_connection_status(
    db: Session,
    *,
    user: User,
    provider_key: str,
    connection_status: str,
    detail: str | None = None,
) -> None:
    provider = get_provider_record(db, provider_key)
    existing = get_user_integration(db, user_id=user.id, provider_id=provider.id)
    existing_tokens = (
        db.scalars(select(IntegrationToken).where(IntegrationToken.user_integration_id == existing.id)).all()
        if existing is not None
        else []
    )
    preserve_connection = bool(
        existing is not None
        and existing.status == "connected"
        and any(token.encrypted_access_token for token in existing_tokens)
        and connection_status in {"connecting", "error"}
    )
    activity_status = connection_status
    if preserve_connection and existing is not None:
        existing.last_error = detail if connection_status == "error" else None
        activity_status = "upgrade_error" if connection_status == "error" else "upgrade_pending"
    else:
        set_user_integration_status(
            db,
            user_id=user.id,
            provider_key=provider_key,
            status=connection_status,
            last_error=detail if connection_status == "error" else None,
        )
    write_activity(
        db,
        user_id=user.id,
        agent="system",
        service=provider_key,
        action="oauth_connection",
        status=activity_status,
        error=detail if connection_status == "error" else None,
    )


def oauth_error_redirect(db: Session, *, user: User, provider_key: str, detail: object | None = None) -> RedirectResponse:
    message = oauth_error_message(provider_key, detail)
    mark_oauth_connection_status(
        db,
        user=user,
        provider_key=provider_key,
        connection_status="error",
        detail=message,
    )
    db.commit()
    return finish_redirect(RedirectResponse(dashboard_redirect()))


def provider_oauth_is_configured(provider_key: str) -> bool:
    if provider_key not in PROVIDERS:
        return False
    auth_type = PROVIDERS[provider_key].auth_type
    if provider_key in MANUAL_SECRET_PROVIDER_KEYS or auth_type in {"api_key", "webhook", "bot_token"}:
        return True

    settings = get_settings()
    if provider_key in {"google", "youtube"}:
        return bool(settings.google_client_id and settings.google_client_secret and settings.google_connected_redirect_uri)
    if provider_key in {"instagram", "facebook"}:
        return bool(settings.meta_app_id and settings.meta_app_secret and settings.meta_redirect_uri)
    if provider_key == "linkedin":
        return bool(
            settings.linkedin_client_id
            and settings.linkedin_client_secret
            and oauth_redirect_uri_is_valid(provider_key, settings.linkedin_redirect_uri)
        )
    if provider_key == "shopify":
        return shopify_oauth_is_configured()
    if provider_key in GENERIC_OAUTH_DEFAULTS:
        try:
            generic_oauth_config(provider_key)
        except HTTPException:
            return False
        return True
    return False


def with_provider_setup_status(payload: dict[str, Any]) -> dict[str, Any]:
    for provider in payload.get("providers", []):
        if not isinstance(provider, dict):
            continue
        provider_key = str(provider.get("key") or "")
        configured = provider_oauth_is_configured(provider_key)
        provider["configured"] = configured
        if configured or provider.get("connected"):
            continue
        auth_type = str(provider.get("authType") or "")
        if auth_type in {"oauth2", "meta_oauth2"}:
            provider["connectionState"] = "unavailable"
            provider["status"] = "Unavailable"
            provider["lastError"] = PUBLIC_OAUTH_SETUP_ERROR
    return payload


def unique_scopes(*groups: tuple[str, ...]) -> tuple[str, ...]:
    values: list[str] = []
    seen: set[str] = set()
    for group in groups:
        for scope in group:
            if scope and scope not in seen:
                values.append(scope)
                seen.add(scope)
    return tuple(values)


def meta_oauth_scopes(provider_key: Literal["instagram", "facebook"]) -> tuple[str, ...]:
    required = ("public_profile", "pages_show_list", "pages_read_engagement")
    if provider_key == "instagram":
        required = (*required, "instagram_basic", "business_management")
    return unique_scopes(PROVIDERS[provider_key].scopes, required)


def linkedin_oauth_scopes() -> tuple[str, ...]:
    configured = provider_env_value("linkedin", "SCOPES")
    if configured:
        return parse_scopes(configured)
    return ("openid", "profile", "email", "w_member_social")


def provider_from_state(state: str, allowed: set[str], user_id: int) -> str:
    parts = state.split(":", 2)
    if len(parts) != 3 or parts[0] not in allowed:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid OAuth state")
    try:
        state_user_id = int(parts[1])
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid OAuth state") from exc
    if state_user_id != user_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid OAuth state")
    return parts[0]


def token_expires_at(token_data: dict[str, Any]) -> datetime | None:
    expires_in = token_data.get("expires_in")
    try:
        seconds = int(expires_in)
    except (TypeError, ValueError):
        return None
    return datetime.now(UTC) + timedelta(seconds=seconds)


def meta_graph_url(path: str) -> str:
    version = get_settings().meta_graph_api_version.strip().strip("/") or "v23.0"
    return f"https://graph.facebook.com/{version}/{path.strip('/')}"


async def exchange_meta_code(code: str, redirect_uri: str) -> dict[str, Any]:
    settings = get_settings()
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.get(
            meta_graph_url("oauth/access_token"),
            params={
                "client_id": settings.meta_app_id,
                "client_secret": settings.meta_app_secret,
                "redirect_uri": redirect_uri,
                "code": code,
            },
        )
    payload = response.json() if response.content else {}
    if response.status_code >= 400 or not isinstance(payload, dict) or not payload.get("access_token"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Meta token exchange failed")
    return payload


async def exchange_meta_long_lived_token(token_data: dict[str, Any]) -> dict[str, Any]:
    settings = get_settings()
    access_token = str(token_data.get("access_token") or "")
    if not access_token:
        return token_data
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.get(
                meta_graph_url("oauth/access_token"),
                params={
                    "grant_type": "fb_exchange_token",
                    "client_id": settings.meta_app_id,
                    "client_secret": settings.meta_app_secret,
                    "fb_exchange_token": access_token,
                },
            )
            payload = response.json() if response.content else {}
    except (httpx.HTTPError, ValueError):
        return token_data
    if response.status_code >= 400 or not isinstance(payload, dict) or not payload.get("access_token"):
        return token_data
    return {**token_data, **payload}


async def meta_pages(access_token: str) -> list[dict[str, Any]]:
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.get(
            meta_graph_url("me/accounts"),
            params={
                "access_token": access_token,
                "fields": "id,name,access_token,instagram_business_account{id,username,name}",
                "limit": "50",
            },
        )
    payload = response.json() if response.content else {}
    if response.status_code >= 400 or not isinstance(payload, dict):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Meta account lookup failed")
    pages = payload.get("data")
    return pages if isinstance(pages, list) else []


async def store_meta_oauth_account(
    db: Session,
    *,
    user: User,
    provider_key: Literal["instagram", "facebook"],
    token_data: dict[str, Any],
) -> None:
    access_token = str(token_data.get("access_token") or "")
    if not access_token:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Meta did not return an access token")
    pages = await meta_pages(access_token)

    if provider_key == "instagram":
        page = next((item for item in pages if isinstance(item.get("instagram_business_account"), dict)), None)
        if not page:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No Instagram Business Account connected to a Facebook Page",
            )
        instagram = page["instagram_business_account"]
        ig_user_id = str(instagram.get("id") or "")
        username = str(instagram.get("username") or "").strip()
        page_name = str(page.get("name") or "Facebook Page")
        if not ig_user_id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Instagram account lookup failed")
        upsert_connected_account(
            db,
            user_id=user.id,
            provider_key="instagram",
            account_identifier=ig_user_id,
            account_label=f"@{username}" if username else page_name,
            account_type="instagram_business",
            access_token=access_token,
            refresh_token=token_data.get("refresh_token"),
            token_type=token_data.get("token_type") or "Bearer",
            expires_at=token_expires_at(token_data),
            scopes=token_data.get("scope"),
            metadata_json={
                "username": username,
                "businessAccount": page_name,
                "pageId": str(page.get("id") or ""),
                "pageName": page_name,
                "source": "meta_oauth",
            },
        )
        legacy = db.scalar(select(InstagramIntegration).where(InstagramIntegration.user_id == user.id))
        if legacy:
            legacy.encrypted_access_token = encrypt_token(access_token)
            legacy.ig_user_id = ig_user_id
            legacy.username = username or None
        else:
            db.add(
                InstagramIntegration(
                    user_id=user.id,
                    encrypted_access_token=encrypt_token(access_token),
                    ig_user_id=ig_user_id,
                    username=username or None,
                )
            )
        return

    page = pages[0] if pages else None
    if not page:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No Facebook Page available for this account")
    page_id = str(page.get("id") or "")
    page_name = str(page.get("name") or "Facebook Page")
    page_access_token = str(page.get("access_token") or access_token)
    upsert_connected_account(
        db,
        user_id=user.id,
        provider_key="facebook",
        account_identifier=page_id or page_name,
        account_label=page_name,
        account_type="facebook_page",
        access_token=page_access_token,
        refresh_token=token_data.get("refresh_token"),
        token_type=token_data.get("token_type") or "Bearer",
        expires_at=token_expires_at(token_data),
        scopes=token_data.get("scope"),
        metadata_json={"pageId": page_id, "pageName": page_name, "source": "meta_oauth"},
    )


async def exchange_linkedin_code(code: str, redirect_uri: str) -> dict[str, Any]:
    settings = get_settings()
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(
            settings.linkedin_token_uri,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "client_id": settings.linkedin_client_id,
                "client_secret": settings.linkedin_client_secret,
                "redirect_uri": redirect_uri,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
    payload = response.json() if response.content else {}
    if response.status_code >= 400 or not isinstance(payload, dict) or not payload.get("access_token"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="LinkedIn token exchange failed")
    return payload


async def linkedin_userinfo(access_token: str) -> dict[str, str]:
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.get(
                "https://api.linkedin.com/v2/userinfo",
                headers={"Authorization": f"Bearer {access_token}"},
            )
            payload = response.json() if response.content else {}
    except (httpx.HTTPError, ValueError):
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    name = str(payload.get("name") or "").strip()
    return {
        "id": str(payload.get("sub") or payload.get("id") or ""),
        "name": name or str(payload.get("email") or "LinkedIn member"),
        "email": str(payload.get("email") or ""),
    }


async def linkedin_company_name(access_token: str) -> str | None:
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.get(
                "https://api.linkedin.com/v2/organizationAcls",
                params={
                    "q": "roleAssignee",
                    "role": "ADMINISTRATOR",
                    "state": "APPROVED",
                    "projection": "(elements*(organization~(id,localizedName)))",
                },
                headers={"Authorization": f"Bearer {access_token}", "X-Restli-Protocol-Version": "2.0.0"},
            )
            payload = response.json() if response.content else {}
    except (httpx.HTTPError, ValueError):
        return None
    elements = payload.get("elements") if isinstance(payload, dict) else None
    first = elements[0] if isinstance(elements, list) and elements else {}
    organization = first.get("organization~") if isinstance(first, dict) else {}
    name = organization.get("localizedName") if isinstance(organization, dict) else None
    return str(name).strip() if name else None


async def store_linkedin_oauth_account(db: Session, *, user: User, token_data: dict[str, Any]) -> None:
    access_token = str(token_data.get("access_token") or "")
    if not access_token:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="LinkedIn did not return an access token")
    info = await linkedin_userinfo(access_token)
    company = await linkedin_company_name(access_token)
    account_identifier = info["id"] or info["email"] or user.email
    upsert_connected_account(
        db,
        user_id=user.id,
        provider_key="linkedin",
        account_identifier=account_identifier,
        account_label=info["name"],
        account_type="linkedin_member",
        access_token=access_token,
        refresh_token=token_data.get("refresh_token"),
        token_type=token_data.get("token_type") or "Bearer",
        expires_at=token_expires_at(token_data),
        scopes=token_data.get("scope"),
        metadata_json={"name": info["name"], "email": info["email"], "company": company, "source": "linkedin_oauth"},
    )


async def verify_telegram_bot(token: str) -> str | None:
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.get(f"https://api.telegram.org/bot{token}/getMe")
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Telegram bot verification failed") from exc
    try:
        payload = response.json() if response.content else {}
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Telegram verification returned invalid JSON") from exc
    if response.status_code >= 400 or not payload.get("ok"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Telegram bot token is invalid")
    result = payload.get("result") if isinstance(payload.get("result"), dict) else {}
    username = result.get("username")
    return str(username) if username else None


def is_official_zapier_catch_hook_url(value: str) -> bool:
    try:
        parsed = urlparse(value.strip())
        port = parsed.port
    except ValueError:
        return False
    return bool(
        parsed.scheme == "https"
        and parsed.hostname == "hooks.zapier.com"
        and port is None
        and parsed.username is None
        and parsed.password is None
        and not parsed.params
        and not parsed.query
        and not parsed.fragment
        and ZAPIER_CATCH_HOOK_PATH_PATTERN.fullmatch(parsed.path)
    )


async def verify_manual_secret(provider_key: str, secret: str) -> None:
    if provider_key == "zapier":
        if not is_official_zapier_catch_hook_url(secret):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Enter a valid Zapier Catch Hook HTTPS URL.",
            )
        # Never trigger a customer automation merely to validate its URL.
        return

    if provider_key == "openai":
        url = "https://api.openai.com/v1/models"
        headers = {"Accept": "application/json", "Authorization": f"Bearer {secret}"}
        provider_name = "OpenAI"
    elif provider_key == "claude":
        url = "https://api.anthropic.com/v1/models"
        headers = {
            "Accept": "application/json",
            "anthropic-version": "2023-06-01",
            "x-api-key": secret,
        }
        provider_name = "Claude"
    else:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported credential provider")

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.get(url, headers=headers)
            payload = response.json() if response.content else {}
    except httpx.TimeoutException as exc:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail=f"{provider_name} credential verification timed out. Please try again.",
        ) from exc
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"{provider_name} credential verification is temporarily unavailable.",
        ) from exc

    if response.status_code in {status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{provider_name} rejected this credential.",
        )
    if response.status_code >= 400:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"{provider_name} credential verification is temporarily unavailable.",
        )
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"{provider_name} credential verification returned invalid data.",
        )


def token_access_token(config: GenericOAuthConfig, token_data: dict[str, Any]) -> str:
    if config.provider_key == "slack":
        authed_user = token_data.get("authed_user") if isinstance(token_data.get("authed_user"), dict) else {}
        return str(token_data.get("access_token") or authed_user.get("access_token") or "")
    return str(token_data.get("access_token") or "")


def safe_token_metadata(token_data: dict[str, Any]) -> dict[str, Any]:
    sanitized = sanitize_metadata(token_data)
    return sanitized if isinstance(sanitized, dict) else {}


def oauth_token_request_kwargs(config: GenericOAuthConfig, data: dict[str, str]) -> dict[str, Any]:
    headers = {"Accept": "application/json", **(config.token_headers or {})}
    auth: tuple[str, str] | None = None
    if config.token_auth == "basic":
        auth = (config.client_id, config.client_secret)
    elif config.token_auth == "secret_basic":
        # Stripe Connect authenticates its platform secret as the HTTP Basic
        # username, with an empty password. The OAuth client id belongs only in
        # the authorization request.
        auth = (config.client_secret, "")
    else:
        if config.client_id_param == "client_key":
            data["client_key"] = config.client_id
        else:
            data["client_id"] = config.client_id
        data["client_secret"] = config.client_secret

    request_kwargs: dict[str, Any] = {"headers": headers, "auth": auth}
    if config.token_body_format == "json":
        headers["Content-Type"] = "application/json"
        request_kwargs["json"] = data
    else:
        headers["Content-Type"] = "application/x-www-form-urlencoded"
        request_kwargs["data"] = data
    return request_kwargs


def oauth_token_payload_is_success(config: GenericOAuthConfig, payload: dict[str, Any]) -> bool:
    if config.provider_key == "slack" and payload.get("ok") is False:
        return False
    return bool(token_access_token(config, payload))


async def exchange_generic_oauth_code(
    config: GenericOAuthConfig,
    code: str,
    *,
    code_verifier: str | None = None,
) -> dict[str, Any]:
    data: dict[str, str] = {"code": code}
    if config.include_authorization_code_grant_type:
        data["grant_type"] = "authorization_code"
    if config.include_redirect_uri_in_token_exchange:
        data["redirect_uri"] = config.redirect_uri
    if config.authorization_code_extra_params:
        data.update(config.authorization_code_extra_params)
    if config.provider_key == "x":
        if not code_verifier:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="OAuth session expired. Please try again.")
        data["code_verifier"] = code_verifier
    provider_name = PROVIDERS[config.provider_key].name
    try:
        async with httpx.AsyncClient(timeout=25) as client:
            response = await client.post(config.token_uri, **oauth_token_request_kwargs(config, data))
    except httpx.TimeoutException as exc:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail=f"{provider_name} connection timed out. Please try again.",
        ) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"{provider_name} connection is temporarily unavailable.",
        ) from exc
    try:
        payload = response.json() if response.content else {}
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="OAuth token exchange returned invalid JSON") from exc
    if response.status_code >= 400 or not isinstance(payload, dict) or not oauth_token_payload_is_success(config, payload):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"{provider_name} token exchange failed")
    return payload


def generic_userinfo_has_identity(config: GenericOAuthConfig, payload: dict[str, Any]) -> bool:
    provider_key = config.provider_key
    if provider_key == "shopify":
        shop = payload.get("shop") if isinstance(payload.get("shop"), dict) else {}
        domain = normalize_shopify_shop_domain(str(shop.get("myshopify_domain") or shop.get("domain") or ""))
        return bool(domain and (not config.shop_domain or domain == config.shop_domain))
    if provider_key == "tiktok":
        error = payload.get("error") if isinstance(payload.get("error"), dict) else {}
        if error and error.get("code") not in {None, "", "ok"}:
            return False
        data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
        user = data.get("user") if isinstance(data.get("user"), dict) else {}
        return bool(user.get("open_id") or user.get("union_id"))
    if provider_key == "x":
        data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
        return bool(data.get("id") or data.get("username"))
    if provider_key == "discord":
        return bool(payload.get("id"))
    if provider_key == "github":
        return bool(payload.get("id") or payload.get("login"))
    if provider_key == "dropbox":
        return bool(payload.get("account_id") or payload.get("email"))
    if provider_key == "onedrive":
        return bool(payload.get("id") or payload.get("mail") or payload.get("userPrincipalName"))
    return bool(payload)


async def fetch_generic_userinfo(config: GenericOAuthConfig, access_token: str) -> dict[str, Any]:
    if not config.userinfo_uri:
        return {}
    provider_name = PROVIDERS[config.provider_key].name
    headers = {"Accept": "application/json", "Authorization": f"Bearer {access_token}"}
    method = "GET"
    params: dict[str, str] | None = None
    if config.provider_key == "shopify":
        headers.pop("Authorization", None)
        headers["X-Shopify-Access-Token"] = access_token
    elif config.provider_key == "dropbox":
        method = "POST"
    elif config.provider_key == "tiktok":
        params = {"fields": "open_id,union_id,avatar_url,display_name"}
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            if method == "POST":
                response = await client.post(config.userinfo_uri, headers=headers)
            else:
                response = await client.get(config.userinfo_uri, headers=headers, params=params)
            payload = response.json() if response.content else {}
    except httpx.TimeoutException as exc:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail=f"{provider_name} account verification timed out. Please try again.",
        ) from exc
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"{provider_name} account verification is temporarily unavailable.",
        ) from exc
    if response.status_code >= 400 or not isinstance(payload, dict) or not generic_userinfo_has_identity(config, payload):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{provider_name} account could not be verified. Please reconnect and try again.",
        )
    return payload


def generic_account_identity(
    config: GenericOAuthConfig,
    *,
    token_data: dict[str, Any],
    userinfo: dict[str, Any],
    fallback_email: str,
) -> tuple[str, str]:
    provider_key = config.provider_key
    if provider_key == "shopify":
        shop = userinfo.get("shop") if isinstance(userinfo.get("shop"), dict) else {}
        domain = normalize_shopify_shop_domain(
            str(shop.get("myshopify_domain") or shop.get("domain") or config.shop_domain or shopify_store_domain() or "")
        )
        name = str(shop.get("name") or domain or "Shopify Store")
        return domain or name, name
    if provider_key == "slack":
        team = token_data.get("team") if isinstance(token_data.get("team"), dict) else {}
        team_id = str(team.get("id") or token_data.get("team_id") or "")
        team_name = str(team.get("name") or token_data.get("team_name") or "Slack Workspace")
        return team_id or team_name, team_name
    if provider_key == "notion":
        workspace_id = str(token_data.get("workspace_id") or token_data.get("owner_user_id") or "")
        workspace_name = str(token_data.get("workspace_name") or "Notion Workspace")
        return workspace_id or workspace_name, workspace_name
    if provider_key == "stripe":
        stripe_user_id = str(token_data.get("stripe_user_id") or "")
        return stripe_user_id or "stripe-account", stripe_user_id or "Stripe Account"
    if provider_key == "tiktok":
        data = userinfo.get("data") if isinstance(userinfo.get("data"), dict) else {}
        user = data.get("user") if isinstance(data.get("user"), dict) else {}
        display_name = str(user.get("display_name") or "")
        account_id = str(user.get("open_id") or user.get("union_id") or fallback_email)
        return account_id, display_name or "TikTok Account"
    if provider_key == "github":
        login = str(userinfo.get("login") or "")
        return str(userinfo.get("id") or login or fallback_email), f"@{login}" if login else "GitHub Account"
    if provider_key == "dropbox":
        name = userinfo.get("name") if isinstance(userinfo.get("name"), dict) else {}
        label = str(name.get("display_name") or userinfo.get("email") or "Dropbox Account")
        return str(userinfo.get("account_id") or userinfo.get("email") or fallback_email), label
    if provider_key == "discord":
        username = str(userinfo.get("username") or "")
        discriminator = str(userinfo.get("discriminator") or "")
        legacy_username = f"{username}#{discriminator}" if username and discriminator and discriminator != "0" else username
        label = str(userinfo.get("global_name") or legacy_username or "")
        return str(userinfo.get("id") or label or fallback_email), label or "Discord Account"
    if provider_key == "onedrive":
        email = str(userinfo.get("mail") or userinfo.get("userPrincipalName") or "")
        name = str(userinfo.get("displayName") or email or "Microsoft Account")
        return str(userinfo.get("id") or email or fallback_email), name
    if provider_key == "x":
        data = userinfo.get("data") if isinstance(userinfo.get("data"), dict) else {}
        username = str(data.get("username") or "")
        name = str(data.get("name") or "")
        return str(data.get("id") or username or fallback_email), f"@{username}" if username else name or "X Account"
    account_id = str(
        userinfo.get("account_id")
        or userinfo.get("account_id")
        or userinfo.get("id")
        or token_data.get("account_id")
        or token_data.get("user_id")
        or fallback_email
    )
    label = str(
        userinfo.get("name")
        or userinfo.get("display_name")
        or userinfo.get("email")
        or token_data.get("account_name")
        or PROVIDERS[provider_key].name
    )
    return account_id, label


async def store_generic_oauth_account(
    db: Session,
    *,
    user: User,
    config: GenericOAuthConfig,
    token_data: dict[str, Any],
) -> None:
    access_token = token_access_token(config, token_data)
    if not access_token:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="OAuth provider did not return an access token")
    userinfo = await fetch_generic_userinfo(config, access_token)
    account_identifier, account_label = generic_account_identity(
        config,
        token_data=token_data,
        userinfo=userinfo,
        fallback_email=user.email,
    )
    metadata_json: dict[str, Any] = {
        "source": "generic_oauth",
        "provider": config.provider_key,
        "token": safe_token_metadata(token_data),
        "account": safe_token_metadata(userinfo),
    }
    if config.provider_key == "shopify" and config.shop_domain:
        metadata_json["shopDomain"] = config.shop_domain
    upsert_connected_account(
        db,
        user_id=user.id,
        provider_key=config.provider_key,
        account_identifier=account_identifier,
        account_label=account_label,
        account_type=config.account_type,
        access_token=access_token,
        refresh_token=token_data.get("refresh_token"),
        token_type=token_data.get("token_type") or "Bearer",
        expires_at=token_expires_at(token_data),
        scopes=token_data.get("scope") or " ".join(config.scopes),
        metadata_json=metadata_json,
    )


def normalized_datetime(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def shopify_shop_domain_for_account(account: IntegrationAccount | None) -> str:
    if account is None:
        return ""
    metadata = account.metadata_json if isinstance(account.metadata_json, dict) else {}
    stored_account = metadata.get("account") if isinstance(metadata.get("account"), dict) else {}
    stored_shop = stored_account.get("shop") if isinstance(stored_account.get("shop"), dict) else {}
    candidates = (
        metadata.get("shopDomain"),
        metadata.get("shop_domain"),
        stored_shop.get("myshopify_domain"),
        stored_shop.get("domain"),
        account.account_identifier,
    )
    for candidate in candidates:
        normalized = normalize_shopify_shop_domain(str(candidate or ""))
        if normalized:
            return normalized
    return ""


def refresh_config_for_provider(provider_key: str, *, shop_domain: str | None = None) -> GenericOAuthConfig | None:
    settings = get_settings()
    if provider_key in {"google", "youtube"}:
        if not settings.google_client_id or not settings.google_client_secret:
            return None
        return GenericOAuthConfig(
            provider_key=provider_key,
            auth_uri="",
            token_uri=settings.google_token_uri,
            client_id=settings.google_client_id,
            client_secret=settings.google_client_secret,
            redirect_uri=oauth_redirect(provider_key),
            scopes=google_connected_scopes(provider_key),
            account_type="google_oauth",
        )
    if provider_key == "linkedin":
        if not settings.linkedin_client_id or not settings.linkedin_client_secret:
            return None
        return GenericOAuthConfig(
            provider_key=provider_key,
            auth_uri="",
            token_uri=settings.linkedin_token_uri,
            client_id=settings.linkedin_client_id,
            client_secret=settings.linkedin_client_secret,
            redirect_uri=oauth_redirect(provider_key),
            scopes=linkedin_oauth_scopes(),
            account_type="linkedin_member",
        )
    if provider_key in GENERIC_OAUTH_DEFAULTS:
        return generic_oauth_config(provider_key, shop_domain=shop_domain if provider_key == "shopify" else None)
    return None


async def exchange_refresh_token(config: GenericOAuthConfig, refresh_token: str) -> dict[str, Any]:
    data: dict[str, str] = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
    }
    provider_name = PROVIDERS[config.provider_key].name
    try:
        async with httpx.AsyncClient(timeout=25) as client:
            response = await client.post(config.token_uri, **oauth_token_request_kwargs(config, data))
    except httpx.TimeoutException as exc:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail=f"{provider_name} connection timed out. Please try again.",
        ) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"{provider_name} connection is temporarily unavailable.",
        ) from exc
    try:
        payload = response.json() if response.content else {}
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="OAuth refresh returned invalid JSON") from exc
    if response.status_code >= 400 or not isinstance(payload, dict) or not oauth_token_payload_is_success(config, payload):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="OAuth refresh failed")
    return payload


async def refresh_due_oauth_tokens(db: Session, user: User) -> None:
    now = datetime.now(UTC)
    refresh_before = now + timedelta(minutes=5)
    integrations = db.scalars(select(UserIntegration).where(UserIntegration.user_id == user.id)).all()
    provider_ids = {integration.provider_id for integration in integrations}
    providers = {
        provider.id: provider
        for provider in (
            db.scalars(select(IntegrationProvider).where(IntegrationProvider.id.in_(provider_ids))).all()
            if provider_ids
            else []
        )
    }
    integration_ids = [integration.id for integration in integrations]
    token_records = (
        db.scalars(select(IntegrationToken).where(IntegrationToken.user_integration_id.in_(integration_ids))).all()
        if integration_ids
        else []
    )
    tokens_by_integration: dict[int, list[IntegrationToken]] = {}
    for token in token_records:
        tokens_by_integration.setdefault(token.user_integration_id, []).append(token)
    account_ids = {token.integration_account_id for token in token_records}
    accounts = {
        account.id: account
        for account in (
            db.scalars(select(IntegrationAccount).where(IntegrationAccount.id.in_(account_ids))).all()
            if account_ids
            else []
        )
    }

    due: list[tuple[UserIntegration, IntegrationToken, datetime, GenericOAuthConfig]] = []
    for integration in integrations:
        if integration.status not in {"connected", "expired", "reconnect_required"}:
            continue
        provider = providers.get(integration.provider_id)
        if provider is None or provider.key in {"telegram", "instagram", "facebook"}:
            continue
        if provider.auth_type in {"api_key", "webhook", "bot_token"}:
            continue
        tokens = tokens_by_integration.get(integration.id, [])
        for token in tokens:
            expires_at = normalized_datetime(token.expires_at)
            if expires_at is None or expires_at > refresh_before:
                continue
            if not token.encrypted_refresh_token:
                if expires_at <= now:
                    integration.status = "expired"
                    integration.last_error = "Authorization expired. Reconnect this app."
                continue
            account = accounts.get(token.integration_account_id)
            config = refresh_config_for_provider(
                provider.key,
                shop_domain=shopify_shop_domain_for_account(account) if provider.key == "shopify" else None,
            )
            if config is None:
                if expires_at <= now:
                    integration.status = "reconnect_required"
                    integration.last_error = "Authorization could not be refreshed. Reconnect this app."
                continue
            due.append((integration, token, expires_at, config))

    semaphore = asyncio.Semaphore(4)

    async def refresh_one(
        item: tuple[UserIntegration, IntegrationToken, datetime, GenericOAuthConfig],
    ) -> tuple[tuple[UserIntegration, IntegrationToken, datetime, GenericOAuthConfig], dict[str, Any] | None]:
        _integration, token, _expires_at, config = item
        try:
            async with semaphore:
                refreshed = await exchange_refresh_token(config, decrypt_token(token.encrypted_refresh_token or ""))
            return item, refreshed
        except (HTTPException, httpx.HTTPError):
            return item, None

    results = await asyncio.gather(*(refresh_one(item) for item in due)) if due else []
    for (integration, token, expires_at, config), refreshed in results:
        if refreshed is None:
            if expires_at <= now:
                integration.status = "reconnect_required"
                integration.last_error = "Authorization could not be refreshed. Reconnect this app."
            continue
        access_token = token_access_token(config, refreshed)
        if access_token:
            token.encrypted_access_token = encrypt_token(access_token)
        refreshed_refresh_token = str(refreshed.get("refresh_token") or "")
        if refreshed_refresh_token:
            token.encrypted_refresh_token = encrypt_token(refreshed_refresh_token)
        refreshed_expires_at = token_expires_at(refreshed)
        if refreshed_expires_at:
            token.expires_at = refreshed_expires_at
        token.token_type = refreshed.get("token_type") or token.token_type
        token.scopes = refreshed.get("scope") or token.scopes
        integration.status = "connected"
        integration.last_error = None
        integration.disconnected_at = None


@router.get("/api/connected-apps")
def connected_apps(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    # Status reads must stay bounded and side-effect free. Token refresh runs
    # only immediately before an action that needs the token; provider network
    # latency must never hold the Dashboard status request or its DB session.
    return with_provider_setup_status(provider_status_payload(db, user))


def oauth_authorization_url(
    provider_key: str,
    user: User,
    *,
    shop_domain: str | None = None,
    youtube_access: YouTubeAccessMode = "growth",
) -> tuple[str, str, str | None, str | None]:
    if provider_key not in PROVIDERS:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown provider")
    if provider_key in MANUAL_SECRET_PROVIDER_KEYS or PROVIDERS[provider_key].auth_type in {"api_key", "webhook", "bot_token"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{PROVIDERS[provider_key].name} uses manual account connection, not OAuth.",
        )

    settings = get_settings()
    state = f"{provider_key}:{user.id}:{secrets.token_urlsafe(24)}"

    if provider_key in {"google", "youtube"}:
        if not settings.google_client_id or not settings.google_client_secret:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=PUBLIC_OAUTH_SETUP_ERROR)
        builder = OAuthUrlBuilder(
            auth_uri=settings.google_auth_uri,
            client_id=settings.google_client_id,
            redirect_uri=oauth_redirect(provider_key),
            scopes=google_connected_scopes(provider_key, youtube_access=youtube_access),
            extra_params={"access_type": "offline", "prompt": "consent select_account"},
        )
    elif provider_key in {"instagram", "facebook"}:
        if not settings.meta_app_id or not settings.meta_app_secret:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=PUBLIC_OAUTH_SETUP_ERROR)
        builder = OAuthUrlBuilder(
            auth_uri=settings.meta_oauth_uri,
            client_id=settings.meta_app_id,
            redirect_uri=oauth_redirect(provider_key),
            scopes=meta_oauth_scopes(provider_key),
            extra_params={"auth_type": "rerequest"},
        )
    elif provider_key == "linkedin":
        if (
            not settings.linkedin_client_id
            or not settings.linkedin_client_secret
            or not oauth_redirect_uri_is_valid(provider_key, settings.linkedin_redirect_uri)
        ):
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=PUBLIC_OAUTH_SETUP_ERROR)
        builder = OAuthUrlBuilder(
            auth_uri=settings.linkedin_auth_uri,
            client_id=settings.linkedin_client_id,
            redirect_uri=oauth_redirect(provider_key),
            scopes=linkedin_oauth_scopes(),
        )
    else:
        config = generic_oauth_config(provider_key, shop_domain=shop_domain if provider_key == "shopify" else None)
        code_verifier = secrets.token_urlsafe(48) if provider_key == "x" else None
        expected_shop_domain = shopify_store_domain(shop_domain) if provider_key == "shopify" else None
        return build_generic_oauth_url(config, state=state, code_verifier=code_verifier), state, code_verifier, expected_shop_domain

    return builder.get_connect_url(state=state), state, None, None


@router.post("/api/connected-apps/{provider_key}/connect")
def connect_oauth_provider(
    provider_key: str,
    payload: OAuthConnectRequest | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> JSONResponse:
    requested_shop_domain = payload.shop_domain if provider_key == "shopify" and payload else None
    youtube_access = payload.youtube_access if provider_key == "youtube" and payload else "growth"
    authorization_url, state, code_verifier, expected_shop_domain = oauth_authorization_url(
        provider_key,
        user,
        shop_domain=requested_shop_domain,
        youtube_access=youtube_access,
    )
    mark_oauth_connection_status(db, user=user, provider_key=provider_key, connection_status="connecting")
    db.commit()
    response = JSONResponse({"authorizationUrl": authorization_url})
    set_state_cookie(response, state)
    set_pkce_cookie(response, code_verifier)
    set_shopify_shop_cookie(response, expected_shop_domain)
    return response


@router.get("/api/connected-apps/{provider_key}/start")
def start_oauth_connection(
    provider_key: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    authorization_url, state, code_verifier, expected_shop_domain = oauth_authorization_url(provider_key, user)
    mark_oauth_connection_status(db, user=user, provider_key=provider_key, connection_status="connecting")
    db.commit()
    response = RedirectResponse(authorization_url)
    set_state_cookie(response, state)
    set_pkce_cookie(response, code_verifier)
    set_shopify_shop_cookie(response, expected_shop_domain)
    return response


@router.get("/api/connected-apps/google/callback")
async def google_connected_callback(
    request: Request,
    state: str = Query(...),
    code: str | None = Query(default=None),
    error: str | None = Query(default=None),
    error_description: str | None = Query(default=None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    validate_state(request, state)
    provider_key = provider_from_state(state, {"google", "youtube"}, user.id)
    if error or not code:
        return oauth_error_redirect(db, user=user, provider_key=provider_key, detail=error_description or error)
    try:
        token_data = await exchange_google_code(code=code, redirect_uri=oauth_redirect(provider_key))
        accounts = await store_google_oauth_accounts(
            db,
            user=user,
            token_data=token_data,
            provider_keys=(provider_key,),  # type: ignore[arg-type]
        )
        if not accounts:
            provider_name = PROVIDERS[provider_key].name
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"{provider_name} permissions were not granted")
    except HTTPException as exc:
        return oauth_error_redirect(db, user=user, provider_key=provider_key, detail=exc.detail)
    db.commit()
    return finish_redirect(RedirectResponse(dashboard_redirect()))


@router.get("/api/connected-apps/meta/callback")
async def meta_connected_callback(
    request: Request,
    state: str = Query(...),
    code: str | None = Query(default=None),
    error: str | None = Query(default=None),
    error_description: str | None = Query(default=None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    validate_state(request, state)
    provider_key = provider_from_state(state, {"instagram", "facebook"}, user.id)
    if error or not code:
        return oauth_error_redirect(db, user=user, provider_key=provider_key, detail=error_description or error)
    try:
        token_data = await exchange_meta_code(code=code, redirect_uri=oauth_redirect(provider_key))
        token_data = await exchange_meta_long_lived_token(token_data)
        await store_meta_oauth_account(
            db,
            user=user,
            provider_key=provider_key,  # type: ignore[arg-type]
            token_data=token_data,
        )
    except HTTPException as exc:
        return oauth_error_redirect(db, user=user, provider_key=provider_key, detail=exc.detail)
    db.commit()
    return finish_redirect(RedirectResponse(dashboard_redirect()))


@router.get("/api/connected-apps/linkedin/callback")
async def linkedin_connected_callback(
    request: Request,
    state: str = Query(...),
    code: str | None = Query(default=None),
    error: str | None = Query(default=None),
    error_description: str | None = Query(default=None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    validate_state(request, state)
    provider_from_state(state, {"linkedin"}, user.id)
    if error or not code:
        return oauth_error_redirect(db, user=user, provider_key="linkedin", detail=error_description or error)
    try:
        token_data = await exchange_linkedin_code(code=code, redirect_uri=oauth_redirect("linkedin"))
        await store_linkedin_oauth_account(db, user=user, token_data=token_data)
    except HTTPException as exc:
        return oauth_error_redirect(db, user=user, provider_key="linkedin", detail=exc.detail)
    db.commit()
    return finish_redirect(RedirectResponse(dashboard_redirect()))


@router.get("/api/connected-apps/youtube/callback")
async def youtube_connected_callback(
    request: Request,
    state: str = Query(...),
    code: str | None = Query(default=None),
    error: str | None = Query(default=None),
    error_description: str | None = Query(default=None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    validate_state(request, state)
    provider_from_state(state, {"youtube"}, user.id)
    if error or not code:
        return oauth_error_redirect(db, user=user, provider_key="youtube", detail=error_description or error)
    try:
        token_data = await exchange_google_code(code=code, redirect_uri=oauth_redirect("youtube"))
        accounts = await store_google_oauth_accounts(
            db,
            user=user,
            token_data=token_data,
            provider_keys=("youtube",),
        )
        if not accounts:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="YouTube scopes were not granted")
    except HTTPException as exc:
        return oauth_error_redirect(db, user=user, provider_key="youtube", detail=exc.detail)
    db.commit()
    return finish_redirect(RedirectResponse(dashboard_redirect()))


@router.get("/api/connected-apps/{provider_key}/callback")
async def generic_connected_callback(
    provider_key: str,
    request: Request,
    state: str = Query(...),
    code: str | None = Query(default=None),
    error: str | None = Query(default=None),
    error_description: str | None = Query(default=None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    if provider_key in {"google", "youtube", "instagram", "facebook", "linkedin", "telegram"}:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown OAuth callback")
    validate_state(request, state)
    provider_from_state(state, {provider_key}, user.id)
    if error or not code:
        return oauth_error_redirect(db, user=user, provider_key=provider_key, detail=error_description or error)
    expected_shop_domain = request.cookies.get(INTEGRATION_SHOPIFY_SHOP_COOKIE) if provider_key == "shopify" else None
    config = generic_oauth_config(provider_key, shop_domain=expected_shop_domain)
    if provider_key == "shopify":
        validate_shopify_callback(request, config, expected_shop_domain=expected_shop_domain)
    try:
        token_data = await exchange_generic_oauth_code(
            config,
            code,
            code_verifier=request.cookies.get(INTEGRATION_PKCE_COOKIE),
        )
        await store_generic_oauth_account(db, user=user, config=config, token_data=token_data)
    except HTTPException as exc:
        return oauth_error_redirect(db, user=user, provider_key=provider_key, detail=exc.detail)
    db.commit()
    return finish_redirect(RedirectResponse(dashboard_redirect()))


@router.post("/api/connected-apps/telegram/accounts")
async def connect_telegram_account(
    payload: TelegramAccountConnectRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    bot_username = await verify_telegram_bot(payload.bot_token.strip())
    account = upsert_connected_account(
        db,
        user_id=user.id,
        provider_key="telegram",
        account_identifier=payload.target_chat_id.strip(),
        account_label=payload.label or (f"@{bot_username}" if bot_username else payload.target_chat_id.strip()),
        account_type=payload.account_type,
        access_token=payload.bot_token.strip(),
        token_type="bot",
        scopes=" ".join(PROVIDERS["telegram"].scopes),
        metadata_json={"botUsername": bot_username},
    )
    db.commit()
    return {"ok": True, "accountId": account.id, "botUsername": bot_username}


@router.post("/api/connected-apps/{provider_key}/accounts")
async def connect_manual_secret_account(
    provider_key: str,
    payload: ManualSecretAccountConnectRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    if provider_key not in MANUAL_SECRET_PROVIDER_KEYS:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="This provider does not support manual secret connection")
    secret = payload.secret.strip()
    await verify_manual_secret(provider_key, secret)
    label = (payload.label or PROVIDERS[provider_key].name).strip()
    identifier = (payload.identifier or label or provider_key).strip()
    account = upsert_connected_account(
        db,
        user_id=user.id,
        provider_key=provider_key,
        account_identifier=identifier,
        account_label=label,
        account_type=PROVIDERS[provider_key].auth_type,
        access_token=secret,
        token_type=PROVIDERS[provider_key].auth_type,
        scopes=" ".join(PROVIDERS[provider_key].scopes),
        metadata_json={"source": "manual_secret", "provider": provider_key},
    )
    db.commit()
    return {"ok": True, "accountId": account.id}


@router.post("/api/connected-apps/{provider_key}/disconnect")
def disconnect_connected_app(
    provider_key: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, bool]:
    if provider_key not in PROVIDERS:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown provider")
    disconnect_provider(db, user_id=user.id, provider_key=provider_key)
    if provider_key == "telegram":
        db.execute(delete(TelegramBotIntegration).where(TelegramBotIntegration.user_id == user.id))
    if provider_key == "instagram":
        db.execute(delete(InstagramIntegration).where(InstagramIntegration.user_id == user.id))
    db.commit()
    return {"ok": True}


@router.get("/api/activity/logs")
def activity_logs(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    logs = list_activity(db, user_id=user.id)
    return {
        "items": [
            {
                "id": log.id,
                "agent": log.agent,
                "service": log.service,
                "action": log.action,
                "status": log.status,
                "externalId": log.external_id,
                "error": log.error,
                "metadata": sanitize_metadata(log.metadata_json or {}),
                "createdAt": log.created_at,
            }
            for log in logs
        ]
    }


@router.post("/api/activity/logs")
def write_activity_log(
    payload: ActivityWriteRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    log = write_activity(
        db,
        user_id=user.id,
        agent=payload.agent,
        service=payload.service,
        action=payload.action,
        status=payload.status,
        external_id=payload.external_id,
        error=payload.error,
        metadata_json=payload.metadata,
    )
    db.commit()
    db.refresh(log)
    return {"ok": True, "id": log.id}


@router.get("/api/scheduler/posts")
def scheduled_posts(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    posts = list_scheduled_posts(db, user_id=user.id)
    return {
        "items": [
            {
                "id": post.id,
                "platform": post.platform,
                "accountId": post.account_id,
                "content": post.content,
                "mediaUrl": post.media_url,
                "mediaType": post.media_type,
                "publishAt": post.publish_at,
                "timezone": post.timezone,
                "repeatRule": post.repeat_rule,
                "status": post.status,
                "externalId": post.external_id,
                "error": post.error,
                "createdAt": post.created_at,
            }
            for post in posts
        ]
    }


@router.post("/api/scheduler/posts")
def create_scheduler_post(
    payload: ScheduledPostCreateRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    publish_at = validate_scheduler_fields(
        platform=payload.platform,
        publish_at=payload.publish_at,
        repeat_rule=payload.repeat_rule,
        media_url=payload.media_url,
        timezone_name=payload.timezone,
    )
    account_id = payload.account_id
    if account_id is None:
        account_id = default_connected_account_id(
            db,
            user_id=user.id,
            platform=payload.platform,
        )
    if account_id is not None:
        connected_account_credentials(
            db,
            user_id=user.id,
            platform=payload.platform,
            account_id=account_id,
        )
    post = create_scheduled_post(
        db,
        user_id=user.id,
        platform=payload.platform,
        account_id=account_id,
        content=payload.content.strip(),
        media_url=payload.media_url,
        media_type=payload.media_type,
        publish_at=publish_at,
        timezone=payload.timezone,
        repeat_rule=payload.repeat_rule,
        source=payload.source,
        run_id=payload.run_id,
    )
    db.commit()
    db.refresh(post)
    return {"ok": True, "id": post.id, "status": post.status}


def requested_social_platforms(arguments: dict[str, Any]) -> set[str]:
    raw_platforms = arguments.get("platforms")
    if raw_platforms is None:
        raw_platforms = arguments.get("platform")
    if raw_platforms is None:
        return set()
    values = raw_platforms if isinstance(raw_platforms, list) else [raw_platforms]
    return {str(value).strip().lower() for value in values if str(value).strip()}


def youtube_upload_failure_metadata(arguments: dict[str, Any]) -> dict[str, Any]:
    account_id = arguments.get("account_id") or arguments.get("accountId")
    metadata: dict[str, Any] = {"tool": "upload_youtube_video"}
    if account_id is not None:
        metadata["accountId"] = account_id
    run_id = arguments.get("run_id") or arguments.get("runId")
    if run_id:
        metadata["runId"] = str(run_id)[:80]
    task_id = youtube_publish_task_id(arguments)
    if task_id is not None:
        metadata["taskId"] = task_id
    return metadata


def youtube_publish_task_id(arguments: dict[str, Any]) -> int | None:
    raw_task_id = arguments.get("task_id") or arguments.get("taskId")
    if raw_task_id is None:
        return None
    try:
        task_id = int(raw_task_id)
    except (TypeError, ValueError):
        return None
    return task_id if task_id > 0 else None


def prior_youtube_publish_result(
    db: Session,
    user: User,
    *,
    task_id: int | None,
    run_id: str | None,
) -> dict[str, Any] | None:
    """Return a completed YouTube result for a safe sequential retry.

    Office publish actions carry a durable Task/run id. Reusing its successful
    result avoids uploading the same video twice when the browser retries after
    a lost response.
    """

    if task_id is None and not run_id:
        return None
    task = find_publish_task(db, user, task_id=task_id, run_id=run_id)
    result_json = task.result_json if task is not None and isinstance(task.result_json, dict) else {}
    results = result_json.get("publishResults") if isinstance(result_json.get("publishResults"), list) else []
    for result in results:
        if not isinstance(result, dict) or result.get("platform") != "youtube" or result.get("ok") is not True:
            continue
        video_id = str(result.get("external_id") or result.get("externalId") or "")
        if not video_id:
            continue
        return {
            "platform": "youtube",
            "videoId": video_id,
            "url": str(result.get("url") or f"https://www.youtube.com/watch?v={video_id}"),
            "privacyStatus": "private",
            "idempotentReplay": True,
        }
    return None


@router.post("/api/agent-tools/execute")
async def execute_agent_tool(
    payload: AgentToolExecuteRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    tool = payload.tool.strip()
    args = payload.arguments
    requested_platforms = requested_social_platforms(args)
    should_upload_youtube = tool == "upload_youtube_video" or (
        tool == "publish_social_post" and "youtube" in requested_platforms
    )
    if should_upload_youtube:
        if not get_settings().youtube_upload_runtime_enabled:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=(
                    "YouTube upload is temporarily disabled until durable idempotency "
                    "and DNS-pinned media downloads are enabled."
                ),
            )
        if tool == "publish_social_post" and requested_platforms != {"youtube"}:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Publish a YouTube video as a separate agent action.",
            )
        task_id = youtube_publish_task_id(args)
        run_id = str(args.get("run_id") or args.get("runId") or "")[:80] or None
        prior_result = prior_youtube_publish_result(db, user, task_id=task_id, run_id=run_id)
        if prior_result is not None:
            return {"ok": True, "result": prior_result}
        await refresh_due_oauth_tokens(db, user)
        try:
            request, result = publish_youtube_video(db, user_id=user.id, arguments=args)
        except YouTubePublishError as exc:
            if exc.reconnect_required:
                set_user_integration_status(
                    db,
                    user_id=user.id,
                    provider_key="youtube",
                    status="reconnect_required",
                    last_error=exc.detail,
                )
            write_activity(
                db,
                user_id=user.id,
                agent=str(args.get("agent") or args.get("source") or "dev")[:120],
                service="youtube",
                action="upload_video",
                status="failed",
                error=exc.detail[:500],
                metadata_json=youtube_upload_failure_metadata(args),
            )
            update_publish_task_from_results(
                db,
                user,
                task_id=youtube_publish_task_id(args),
                run_id=str(args.get("run_id") or args.get("runId") or "")[:80] or None,
                results=[PublishTargetResult(platform="youtube", ok=False, error=exc.detail)],
            )
            db.commit()
            raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
        write_activity(
            db,
            user_id=user.id,
            agent=str(request.source or args.get("agent") or "dev")[:120],
            service="youtube",
            action="upload_video",
            status="published",
            external_id=result.video_id,
            metadata_json={
                "accountId": result.account_id,
                "channel": result.account_identifier,
                "privacyStatus": result.privacy_status,
                "mediaHost": result.media_host,
                "mediaBytes": result.media_size,
                "runId": request.run_id,
                "taskId": youtube_publish_task_id(args),
            },
        )
        update_publish_task_from_results(
            db,
            user,
            task_id=youtube_publish_task_id(args),
            run_id=request.run_id,
            results=[
                PublishTargetResult(
                    platform="youtube",
                    ok=True,
                    external_id=result.video_id,
                    url=result.url,
                )
            ],
        )
        db.commit()
        return {
            "ok": True,
            "result": {
                "platform": "youtube",
                "videoId": result.video_id,
                "url": result.url,
                "privacyStatus": result.privacy_status,
                "accountId": result.account_id,
            },
        }
    if is_google_agent_tool(tool):
        if get_settings().is_production and tool in GOOGLE_WRITE_AGENT_TOOLS:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    "Google write actions are disabled in production until durable idempotency "
                    "and unknown-outcome reconciliation are available."
                ),
            )
        await refresh_due_oauth_tokens(db, user)
        try:
            execution = await execute_google_agent_tool(db, user_id=user.id, tool=tool, arguments=args)
        except HTTPException as exc:
            write_activity(
                db,
                user_id=user.id,
                agent=str(args.get("agent") or "agent")[:120],
                service="google",
                action=tool,
                status="failed",
                error=str(exc.detail)[:500],
            )
            db.commit()
            raise
        external_id = (
            execution.result.get("messageId")
            or execution.result.get("draftId")
            or execution.result.get("id")
            or execution.result.get("updatedRange")
        )
        write_activity(
            db,
            user_id=user.id,
            agent=str(args.get("agent") or "agent")[:120],
            service="google",
            action=tool,
            status="completed",
            external_id=external_id,
            metadata_json={"accountId": execution.account_id},
        )
        db.commit()
        return {"ok": True, "result": execution.result}
    if tool == "get_connected_apps_status":
        result = with_provider_setup_status(provider_status_payload(db, user))
        db.commit()
        return {"ok": True, "result": result}
    if tool == "write_activity_log":
        log = write_activity(
            db,
            user_id=user.id,
            agent=str(args.get("agent") or "agent"),
            service=str(args.get("service") or "workspace"),
            action=str(args.get("action") or "tool_action"),
            status=str(args.get("status") or "done"),
            external_id=args.get("external_id"),
            error=args.get("error"),
            metadata_json=args.get("metadata") if isinstance(args.get("metadata"), dict) else None,
        )
        db.commit()
        db.refresh(log)
        return {"ok": True, "result": {"id": log.id}}
    if tool in {"schedule_social_post", "schedule_task"}:
        publish_at = args.get("publish_at") or args.get("publishAt")
        if not isinstance(publish_at, str):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="publish_at is required")
        try:
            publish_dt = datetime.fromisoformat(publish_at.replace("Z", "+00:00"))
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="publish_at must be ISO datetime") from exc
        platforms = args.get("platforms") or [args.get("platform") or "telegram"]
        if not isinstance(platforms, list):
            platforms = [platforms]
        platforms = [str(platform).strip().lower() for platform in platforms]
        if not platforms or any(not platform for platform in platforms):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="At least one platform is required")
        content = str(args.get("content") or args.get("text") or "").strip()
        if not content:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Scheduled content is required")
        repeat_rule = args.get("repeat_rule") or args.get("repeatRule")
        media_url = args.get("media_url") or args.get("mediaUrl")
        raw_account_id = args.get("account_id") or args.get("accountId")
        account_id: int | None = None
        if raw_account_id is not None:
            try:
                account_id = int(raw_account_id)
            except (TypeError, ValueError) as exc:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="accountId must be an integer") from exc
            if account_id <= 0 or len(platforms) != 1:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="A selected account requires exactly one publishing platform.",
                )
            connected_account_credentials(
                db,
                user_id=user.id,
                platform=platforms[0],
                account_id=account_id,
            )
        created = []
        for platform in platforms:
            normalized_publish_at = validate_scheduler_fields(
                platform=platform,
                publish_at=publish_dt,
                repeat_rule=str(repeat_rule) if repeat_rule else None,
                media_url=str(media_url) if media_url else None,
                timezone_name=str(args.get("timezone") or "UTC"),
            )
            post_account_id = account_id
            if post_account_id is None:
                post_account_id = default_connected_account_id(
                    db,
                    user_id=user.id,
                    platform=platform,
                )
                if post_account_id is not None:
                    connected_account_credentials(
                        db,
                        user_id=user.id,
                        platform=platform,
                        account_id=post_account_id,
                    )
            post = create_scheduled_post(
                db,
                user_id=user.id,
                platform=platform,
                account_id=post_account_id,
                content=content,
                media_url=media_url,
                media_type=args.get("media_type") or args.get("mediaType"),
                publish_at=normalized_publish_at,
                timezone=str(args.get("timezone") or "UTC"),
                repeat_rule=repeat_rule,
                source=str(args.get("source") or "agent_tool"),
                run_id=args.get("run_id") or args.get("runId"),
            )
            created.append({"id": post.id, "platform": platform})
        db.commit()
        return {"ok": True, "result": {"scheduled": created}}
    if tool == "publish_social_post":
        return {
            "ok": False,
            "detail": "Immediate publishing is handled by /api/publish/social; pass publish_at to schedule through this tool.",
        }
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Unsupported agent tool: {tool}")


@router.on_event("startup")
def seed_connected_app_providers() -> None:
    # FastAPI router startup hooks do not receive db sessions; main startup seeds via create_all.
    # Provider rows are lazily synchronized on first request.
    return None
