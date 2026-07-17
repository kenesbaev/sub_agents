from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, Literal

import httpx
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.connected_apps.providers import (
    PROVIDERS,
    YOUTUBE_ANALYTICS_READ_SCOPE,
    YOUTUBE_DATA_READ_SCOPE,
    YOUTUBE_UPLOAD_SCOPE,
)
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
YouTubeAccessMode = Literal["growth", "publisher"]


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


def youtube_scopes(access_mode: YouTubeAccessMode = "growth") -> tuple[str, ...]:
    """Return the least-privilege scopes for the requested YouTube workflow.

    Growth analysis is read-only. Publishing scopes are requested only from an
    explicit Publisher connection/upgrade action.
    """

    growth_scopes = (YOUTUBE_DATA_READ_SCOPE, YOUTUBE_ANALYTICS_READ_SCOPE)
    if access_mode == "publisher":
        return unique_scopes(growth_scopes, (YOUTUBE_UPLOAD_SCOPE,))
    return growth_scopes


def google_connected_scopes(
    provider_key: GoogleProviderKey = "google",
    *,
    youtube_access: YouTubeAccessMode = "growth",
) -> tuple[str, ...]:
    if provider_key == "youtube":
        # Teamora already authenticated the user. Connected YouTube needs only
        # YouTube API grants, not a second OIDC profile/email grant.
        return youtube_scopes(youtube_access)
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
    try:
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
    except httpx.TimeoutException as exc:
        raise HTTPException(status_code=status.HTTP_504_GATEWAY_TIMEOUT, detail="Google authorization timed out") from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Google authorization is unavailable") from exc
    if token_response.status_code >= 400:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Google token exchange failed")
    try:
        payload = token_response.json()
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Google token exchange returned invalid data") from exc
    if not isinstance(payload, dict) or not str(payload.get("access_token") or ""):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Google did not return an access token")
    return payload


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
    except httpx.TimeoutException as exc:
        raise HTTPException(status_code=status.HTTP_504_GATEWAY_TIMEOUT, detail="YouTube channel verification timed out") from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="YouTube channel verification is unavailable") from exc
    if response.status_code >= 400:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="YouTube channel could not be verified with the granted permissions",
        )
    try:
        payload = response.json() if response.content else {}
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="YouTube channel verification returned invalid data") from exc

    items = payload.get("items") if isinstance(payload, dict) else None
    first = items[0] if isinstance(items, list) and items else {}
    snippet = first.get("snippet") if isinstance(first, dict) else {}
    title = snippet.get("title") if isinstance(snippet, dict) else None
    channel_id = first.get("id") if isinstance(first, dict) else None
    if not channel_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No YouTube channel was found for the selected Google account",
        )
    return {
        "id": str(channel_id),
        "email": fallback["email"],
        "name": str(title or fallback["name"]),
    }


def google_token_expires_at(token_data: dict[str, Any]) -> datetime:
    return datetime.now(UTC) + timedelta(seconds=int(token_data.get("expires_in") or 3600))


def google_token_scopes(token_data: dict[str, Any], provider_key: GoogleProviderKey) -> str:
    # Never infer grants from the scopes we requested. Capability checks and the
    # UI must reflect only scopes the provider actually returned.
    return str(token_data.get("scope") or "").strip()


def google_token_grants_provider(token_data: dict[str, Any], provider_key: GoogleProviderKey) -> bool:
    scope_text = str(token_data.get("scope") or "")
    if not scope_text:
        return False
    granted = set(scope_text.split())
    if provider_key == "youtube":
        return bool(granted & {YOUTUBE_DATA_READ_SCOPE, YOUTUBE_UPLOAD_SCOPE})
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

    if "google" in provider_keys:
        info = await google_userinfo(access_token, user.email)
    else:
        display_name = " ".join(part for part in (user.first_name, user.last_name) if part).strip()
        info = {"id": user.email, "email": user.email, "name": display_name or user.email}
    accounts: list[IntegrationAccount] = []
    for provider_key in provider_keys:
        if not google_token_grants_provider(token_data, provider_key):
            continue
        account_info = await youtube_channel_info(access_token, info) if provider_key == "youtube" else info
        account = upsert_connected_account(
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
        if provider_key == "youtube":
            # The account selected in the most recent OAuth flow becomes the
            # explicit default used by Publisher when no account id is supplied.
            siblings = db.scalars(
                select(IntegrationAccount).where(
                    IntegrationAccount.user_integration_id == account.user_integration_id,
                )
            ).all()
            for sibling in siblings:
                sibling.is_default = sibling.id == account.id
        accounts.append(account)
    return accounts
