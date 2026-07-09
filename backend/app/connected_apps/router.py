from __future__ import annotations

import base64
import hashlib
import os
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.connected_apps.google_oauth import (
    exchange_google_code,
    google_connected_scopes,
    store_google_oauth_accounts,
)
from app.connected_apps.providers import OAuthUrlBuilder, PROVIDERS
from app.connected_apps.service import (
    create_scheduled_post,
    disconnect_provider,
    list_activity,
    list_scheduled_posts,
    provider_status_payload,
    set_user_integration_status,
    upsert_connected_account,
    write_activity,
)
from app.db.session import get_db
from app.models import IntegrationProvider, IntegrationToken, InstagramIntegration, TelegramBotIntegration, User, UserIntegration
from app.security import get_current_user
from app.token_crypto import decrypt_token, encrypt_token

router = APIRouter(tags=["connected-apps"])

INTEGRATION_STATE_COOKIE = "rebly_integration_oauth_state"
INTEGRATION_PKCE_COOKIE = "rebly_integration_pkce_verifier"
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


class ScheduledPostCreateRequest(BaseModel):
    platform: Literal[
        "telegram",
        "instagram",
        "facebook",
        "linkedin",
        "youtube",
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
        "openai",
        "claude",
        "zapier",
    ]
    content: str = Field(min_length=1, max_length=4096)
    publish_at: datetime
    timezone: str = Field(default="UTC", max_length=80)
    repeat_rule: str | None = Field(default=None, max_length=160)
    media_url: str | None = Field(default=None, max_length=2048)
    media_type: str | None = Field(default=None, max_length=120)
    account_id: int | None = None
    source: str | None = Field(default=None, max_length=80)
    run_id: str | None = Field(default=None, max_length=80)


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
    extra_params: dict[str, str] | None = None


GENERIC_OAUTH_DEFAULTS: dict[str, dict[str, Any]] = {
    "shopify": {
        "auth_uri": "",
        "token_uri": "",
        "account_type": "shopify_store",
        "userinfo_uri": "",
    },
    "tiktok": {
        "auth_uri": "https://www.tiktok.com/v2/auth/authorize/",
        "token_uri": "https://open.tiktokapis.com/v2/oauth/token/",
        "client_id_param": "client_key",
        "account_type": "tiktok_account",
        "userinfo_uri": "https://open.tiktokapis.com/v2/user/info/",
    },
    "x": {
        "auth_uri": "https://twitter.com/i/oauth2/authorize",
        "token_uri": "https://api.twitter.com/2/oauth2/token",
        "account_type": "x_account",
        "userinfo_uri": "https://api.twitter.com/2/users/me?user.fields=username,name",
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
    },
    "notion": {
        "auth_uri": "https://api.notion.com/v1/oauth/authorize",
        "token_uri": "https://api.notion.com/v1/oauth/token",
        "account_type": "notion_workspace",
        "token_auth": "basic",
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
    },
}

MANUAL_SECRET_PROVIDER_KEYS = {"openai", "claude", "zapier"}


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


def provider_scopes(provider_key: str) -> tuple[str, ...]:
    configured = provider_env_value(provider_key, "SCOPES")
    if configured:
        return tuple(scope for scope in configured.replace(",", " ").split() if scope)
    return PROVIDERS[provider_key].scopes


def shopify_store_domain() -> str:
    raw_domain = provider_env_value("shopify", "SHOP_DOMAIN", "STORE_DOMAIN", "SHOPIFY_SHOP_DOMAIN")
    domain = raw_domain.replace("https://", "").replace("http://", "").strip().strip("/")
    if domain and "." not in domain:
        domain = f"{domain}.myshopify.com"
    return domain


def generic_oauth_config(provider_key: str) -> GenericOAuthConfig:
    if provider_key not in GENERIC_OAUTH_DEFAULTS or provider_key not in PROVIDERS:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown OAuth provider")

    defaults = GENERIC_OAUTH_DEFAULTS[provider_key]
    client_id = provider_env_value(provider_key, "CLIENT_ID", "APP_ID", "CLIENT_KEY")
    client_secret = provider_env_value(provider_key, "CLIENT_SECRET", "APP_SECRET", "SECRET")
    redirect_uri = provider_env_value(provider_key, "REDIRECT_URI", default=generic_oauth_redirect(provider_key))
    auth_uri = provider_env_value(provider_key, "AUTH_URI", default=str(defaults.get("auth_uri") or ""))
    token_uri = provider_env_value(provider_key, "TOKEN_URI", default=str(defaults.get("token_uri") or ""))
    userinfo_uri = provider_env_value(provider_key, "USERINFO_URI", default=str(defaults.get("userinfo_uri") or ""))

    if provider_key == "shopify":
        shop_domain = shopify_store_domain()
        if not shop_domain:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=PUBLIC_OAUTH_SETUP_ERROR,
            )
        auth_uri = auth_uri or f"https://{shop_domain}/admin/oauth/authorize"
        token_uri = token_uri or f"https://{shop_domain}/admin/oauth/access_token"
        userinfo_uri = userinfo_uri or f"https://{shop_domain}/admin/api/2025-01/shop.json"

    if not client_id or not client_secret or not auth_uri or not token_uri:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=PUBLIC_OAUTH_SETUP_ERROR,
        )

    return GenericOAuthConfig(
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
        extra_params=dict(defaults.get("extra_params") or {}),
    )


def build_generic_oauth_url(config: GenericOAuthConfig, *, state: str, code_verifier: str | None = None) -> str:
    params = {
        config.client_id_param: config.client_id,
        "redirect_uri": config.redirect_uri,
        "response_type": "code",
        "state": state,
    }
    if config.scopes:
        params["scope"] = " ".join(config.scopes)
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


def validate_state(request: Request, state: str) -> None:
    expected_state = request.cookies.get(INTEGRATION_STATE_COOKIE)
    if not expected_state or expected_state != state:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid OAuth state")


def finish_redirect(response: RedirectResponse) -> RedirectResponse:
    response.delete_cookie(INTEGRATION_STATE_COOKIE, path="/", samesite="lax")
    response.delete_cookie(INTEGRATION_PKCE_COOKIE, path="/", samesite="lax")
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
        status=connection_status,
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
        return bool(settings.linkedin_client_id and settings.linkedin_client_secret and settings.linkedin_redirect_uri)
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
        required = (*required, "business_management")
    return unique_scopes(PROVIDERS[provider_key].scopes, required)


def linkedin_oauth_scopes() -> tuple[str, ...]:
    return unique_scopes(("openid", "profile", "email"), PROVIDERS["linkedin"].scopes)


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


def token_access_token(config: GenericOAuthConfig, token_data: dict[str, Any]) -> str:
    if config.provider_key == "slack":
        authed_user = token_data.get("authed_user") if isinstance(token_data.get("authed_user"), dict) else {}
        return str(token_data.get("access_token") or authed_user.get("access_token") or "")
    return str(token_data.get("access_token") or "")


def safe_token_metadata(token_data: dict[str, Any]) -> dict[str, Any]:
    blocked = {"access_token", "refresh_token", "id_token"}
    metadata: dict[str, Any] = {}
    for key, value in token_data.items():
        if key in blocked:
            continue
        if isinstance(value, (str, int, float, bool)) or value is None:
            metadata[key] = value
        elif isinstance(value, dict):
            metadata[key] = {
                nested_key: nested_value
                for nested_key, nested_value in value.items()
                if isinstance(nested_value, (str, int, float, bool)) or nested_value is None
            }
    return metadata


async def exchange_generic_oauth_code(
    config: GenericOAuthConfig,
    code: str,
    *,
    code_verifier: str | None = None,
) -> dict[str, Any]:
    data: dict[str, str] = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": config.redirect_uri,
    }
    if config.provider_key == "x":
        if not code_verifier:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="OAuth session expired. Please try again.")
        data["code_verifier"] = code_verifier
    if config.client_id_param == "client_key":
        data["client_key"] = config.client_id
    else:
        data["client_id"] = config.client_id
    headers = {"Accept": "application/json"}
    auth: tuple[str, str] | None = None
    if config.token_auth == "basic":
        auth = (config.client_id, config.client_secret)
    else:
        data["client_secret"] = config.client_secret
    async with httpx.AsyncClient(timeout=25) as client:
        response = await client.post(
            config.token_uri,
            data=data,
            headers=headers,
            auth=auth,
        )
    try:
        payload = response.json() if response.content else {}
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="OAuth token exchange returned invalid JSON") from exc
    if response.status_code >= 400 or not isinstance(payload, dict) or not token_access_token(config, payload):
        provider_name = PROVIDERS[config.provider_key].name
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"{provider_name} token exchange failed")
    return payload


async def fetch_generic_userinfo(config: GenericOAuthConfig, access_token: str) -> dict[str, Any]:
    if not config.userinfo_uri:
        return {}
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
    except (httpx.HTTPError, ValueError):
        return {}
    return payload if response.status_code < 400 and isinstance(payload, dict) else {}


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
        domain = str(shop.get("domain") or shop.get("myshopify_domain") or shopify_store_domain() or "")
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
        metadata_json={
            "source": "generic_oauth",
            "provider": config.provider_key,
            "token": safe_token_metadata(token_data),
            "account": safe_token_metadata(userinfo),
        },
    )


def normalized_datetime(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def refresh_config_for_provider(provider_key: str) -> GenericOAuthConfig | None:
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
        return generic_oauth_config(provider_key)
    return None


async def exchange_refresh_token(config: GenericOAuthConfig, refresh_token: str) -> dict[str, Any]:
    data: dict[str, str] = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
    }
    if config.client_id_param == "client_key":
        data["client_key"] = config.client_id
    else:
        data["client_id"] = config.client_id
    headers = {"Accept": "application/json"}
    auth: tuple[str, str] | None = None
    if config.token_auth == "basic":
        auth = (config.client_id, config.client_secret)
    else:
        data["client_secret"] = config.client_secret
    async with httpx.AsyncClient(timeout=25) as client:
        response = await client.post(config.token_uri, data=data, headers=headers, auth=auth)
    try:
        payload = response.json() if response.content else {}
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="OAuth refresh returned invalid JSON") from exc
    if response.status_code >= 400 or not isinstance(payload, dict) or not token_access_token(config, payload):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="OAuth refresh failed")
    return payload


async def refresh_due_oauth_tokens(db: Session, user: User) -> None:
    now = datetime.now(UTC)
    refresh_before = now + timedelta(minutes=5)
    integrations = db.scalars(select(UserIntegration).where(UserIntegration.user_id == user.id)).all()
    for integration in integrations:
        if integration.status not in {"connected", "expired", "reconnect_required"}:
            continue
        provider = db.get(IntegrationProvider, integration.provider_id)
        if provider is None or provider.key in {"telegram", "instagram", "facebook"}:
            continue
        if provider.auth_type in {"api_key", "webhook", "bot_token"}:
            continue
        tokens = db.scalars(
            select(IntegrationToken).where(IntegrationToken.user_integration_id == integration.id)
        ).all()
        for token in tokens:
            expires_at = normalized_datetime(token.expires_at)
            if expires_at is None or expires_at > refresh_before:
                continue
            if not token.encrypted_refresh_token:
                if expires_at <= now:
                    integration.status = "expired"
                    integration.last_error = "Authorization expired. Reconnect this app."
                continue
            try:
                config = refresh_config_for_provider(provider.key)
                if config is None:
                    raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="OAuth refresh is not configured")
                refreshed = await exchange_refresh_token(config, decrypt_token(token.encrypted_refresh_token))
            except HTTPException:
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
async def connected_apps(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    await refresh_due_oauth_tokens(db, user)
    payload = with_provider_setup_status(provider_status_payload(db, user))
    db.commit()
    return payload


def oauth_authorization_url(provider_key: str, user: User) -> tuple[str, str, str | None]:
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
            scopes=google_connected_scopes(provider_key),
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
        if not settings.linkedin_client_id or not settings.linkedin_client_secret:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=PUBLIC_OAUTH_SETUP_ERROR)
        builder = OAuthUrlBuilder(
            auth_uri=settings.linkedin_auth_uri,
            client_id=settings.linkedin_client_id,
            redirect_uri=oauth_redirect(provider_key),
            scopes=linkedin_oauth_scopes(),
        )
    else:
        config = generic_oauth_config(provider_key)
        code_verifier = secrets.token_urlsafe(48) if provider_key == "x" else None
        return build_generic_oauth_url(config, state=state, code_verifier=code_verifier), state, code_verifier

    return builder.get_connect_url(state=state), state, None


@router.post("/api/connected-apps/{provider_key}/connect")
def connect_oauth_provider(
    provider_key: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> JSONResponse:
    authorization_url, state, code_verifier = oauth_authorization_url(provider_key, user)
    mark_oauth_connection_status(db, user=user, provider_key=provider_key, connection_status="connecting")
    db.commit()
    response = JSONResponse({"authorizationUrl": authorization_url})
    set_state_cookie(response, state)
    set_pkce_cookie(response, code_verifier)
    return response


@router.get("/api/connected-apps/{provider_key}/start")
def start_oauth_connection(
    provider_key: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    authorization_url, state, code_verifier = oauth_authorization_url(provider_key, user)
    mark_oauth_connection_status(db, user=user, provider_key=provider_key, connection_status="connecting")
    db.commit()
    response = RedirectResponse(authorization_url)
    set_state_cookie(response, state)
    set_pkce_cookie(response, code_verifier)
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
    try:
        config = generic_oauth_config(provider_key)
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
                "metadata": log.metadata_json or {},
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
    post = create_scheduled_post(
        db,
        user_id=user.id,
        platform=payload.platform,
        account_id=payload.account_id,
        content=payload.content.strip(),
        media_url=payload.media_url,
        media_type=payload.media_type,
        publish_at=payload.publish_at,
        timezone=payload.timezone,
        repeat_rule=payload.repeat_rule,
        source=payload.source,
        run_id=payload.run_id,
    )
    db.commit()
    db.refresh(post)
    return {"ok": True, "id": post.id, "status": post.status}


@router.post("/api/agent-tools/execute")
def execute_agent_tool(
    payload: AgentToolExecuteRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    tool = payload.tool.strip()
    args = payload.arguments
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
        created = []
        for platform in platforms:
            post = create_scheduled_post(
                db,
                user_id=user.id,
                platform=str(platform),
                content=str(args.get("content") or args.get("text") or ""),
                media_url=args.get("media_url") or args.get("mediaUrl"),
                media_type=args.get("media_type") or args.get("mediaType"),
                publish_at=publish_dt,
                timezone=str(args.get("timezone") or "UTC"),
                repeat_rule=args.get("repeat_rule") or args.get("repeatRule"),
                source=str(args.get("source") or "agent_tool"),
                run_id=args.get("run_id") or args.get("runId"),
            )
            created.append({"id": post.id, "platform": str(platform)})
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
