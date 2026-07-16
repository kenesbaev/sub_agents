from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, Literal

import httpx
from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.config import get_settings
from app.connected_apps.providers import PROVIDERS
from app.connected_apps.service import upsert_connected_account
from app.models import IntegrationAccount, User

PROVIDER_KEY = "google"

GOOGLE_WORKSPACE_TOOLS = (
    "search_gmail",
    "read_gmail_thread",
    "create_gmail_draft",
    "send_gmail",
    "reply_gmail",
    "list_calendar_events",
    "find_free_time",
    "create_calendar_event",
    "search_drive_files",
    "create_google_doc",
    "read_google_sheet",
    "append_google_sheet_row",
    "update_google_sheet_row",
)

GOOGLE_BASE_SCOPES = ("openid", "email", "profile")
GoogleProviderKey = Literal["google", "youtube"]


def unique_scopes(*groups: tuple[str, ...]) -> tuple[str, ...]:
    values: list[str] = []
    seen: set[str] = set()
    for group in groups:
        for scope in group:
            if scope and scope not in seen:
                values.append(scope)
                seen.add(scope)
    return tuple(values)


def google_workspace_scopes() -> tuple[str, ...]:
    return PROVIDERS["google"].scopes


def youtube_scopes() -> tuple[str, ...]:
    return PROVIDERS["youtube"].scopes


def google_connected_scopes(provider_key: GoogleProviderKey = "google") -> tuple[str, ...]:
    if provider_key == "youtube":
        return unique_scopes(GOOGLE_BASE_SCOPES, youtube_scopes())
    return unique_scopes(GOOGLE_BASE_SCOPES, google_workspace_scopes())


def google_login_scopes() -> tuple[str, ...]:
    settings = get_settings()
    if not settings.google_login_workspace_scopes:
        return GOOGLE_BASE_SCOPES
    scopes = unique_scopes(GOOGLE_BASE_SCOPES, google_workspace_scopes())
    if settings.google_login_youtube_scopes:
        return unique_scopes(scopes, youtube_scopes())
    return scopes


def google_login_provider_keys() -> tuple[GoogleProviderKey, ...]:
    settings = get_settings()
    if not settings.google_login_workspace_scopes:
        return ()
    if settings.google_login_youtube_scopes:
        return ("google", "youtube")
    return ("google",)


async def exchange_google_code(*, code: str, redirect_uri: str) -> dict[str, Any]:
    settings = get_settings()
    async with httpx.AsyncClient(timeout=20) as client:
        token_response = await client.post(
            settings.google_token_uri,
            data={
                "code": code,
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
        )
    if token_response.status_code >= 400:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Google token exchange failed")
    return token_response.json()


async def google_userinfo(access_token: str, fallback_email: str) -> dict[str, str]:
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.get(
                "https://openidconnect.googleapis.com/v1/userinfo",
                headers={"Authorization": f"Bearer {access_token}"},
            )
            payload = response.json() if response.content else {}
    except (httpx.HTTPError, ValueError):
        payload = {}
    return {
        "id": str(payload.get("sub") or fallback_email),
        "email": str(payload.get("email") or fallback_email),
        "name": str(payload.get("name") or fallback_email),
    }


async def youtube_channel_info(access_token: str, fallback: dict[str, str]) -> dict[str, str]:
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.get(
                "https://www.googleapis.com/youtube/v3/channels",
                params={"part": "snippet", "mine": "true", "maxResults": "1"},
                headers={"Authorization": f"Bearer {access_token}"},
            )
            payload = response.json() if response.content else {}
    except (httpx.HTTPError, ValueError):
        payload = {}

    items = payload.get("items") if isinstance(payload, dict) else None
    first = items[0] if isinstance(items, list) and items else {}
    snippet = first.get("snippet") if isinstance(first, dict) else {}
    title = snippet.get("title") if isinstance(snippet, dict) else None
    channel_id = first.get("id") if isinstance(first, dict) else None
    return {
        "id": str(channel_id or fallback["id"]),
        "email": fallback["email"],
        "name": str(title or fallback["name"]),
    }


def google_token_expires_at(token_data: dict[str, Any]) -> datetime:
    return datetime.now(UTC) + timedelta(seconds=int(token_data.get("expires_in") or 3600))


def google_token_scopes(token_data: dict[str, Any], provider_key: GoogleProviderKey) -> str:
    default_scopes = google_connected_scopes(provider_key)
    return str(token_data.get("scope") or " ".join(default_scopes))


def google_token_grants_provider(token_data: dict[str, Any], provider_key: GoogleProviderKey) -> bool:
    scope_text = str(token_data.get("scope") or "")
    if not scope_text:
        return True
    granted = set(scope_text.split())
    provider_scopes = set(PROVIDERS[provider_key].scopes)
    return bool(granted & provider_scopes)


async def store_google_oauth_accounts(
    db: Session,
    *,
    user: User,
    token_data: dict[str, Any],
    provider_keys: tuple[GoogleProviderKey, ...],
) -> list[IntegrationAccount]:
    access_token = str(token_data.get("access_token") or "")
    if not access_token:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Google did not return an access token")

    info = await google_userinfo(access_token, user.email)
    accounts: list[IntegrationAccount] = []
    for provider_key in provider_keys:
        if not google_token_grants_provider(token_data, provider_key):
            continue
        account_info = await youtube_channel_info(access_token, info) if provider_key == "youtube" else info
        accounts.append(
            upsert_connected_account(
                db,
                user_id=user.id,
                provider_key=provider_key,
                account_identifier=account_info["id"],
                account_label=account_info["name"] if provider_key == "youtube" else account_info["email"],
                account_type="youtube_channel" if provider_key == "youtube" else "google_workspace",
                access_token=access_token,
                refresh_token=token_data.get("refresh_token"),
                token_type=token_data.get("token_type") or "Bearer",
                expires_at=google_token_expires_at(token_data),
                scopes=google_token_scopes(token_data, provider_key),
                metadata_json={
                    "name": account_info["name"],
                    "email": account_info["email"],
                    "source": "google_oauth",
                },
            )
        )
    return accounts
