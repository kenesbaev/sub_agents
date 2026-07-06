from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import RedirectResponse
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
    upsert_connected_account,
    write_activity,
)
from app.db.session import get_db
from app.models import InstagramIntegration, TelegramBotIntegration, User
from app.security import get_current_user
from app.token_crypto import encrypt_token

router = APIRouter(tags=["connected-apps"])

INTEGRATION_STATE_COOKIE = "rebly_integration_oauth_state"


class TelegramAccountConnectRequest(BaseModel):
    bot_token: str = Field(min_length=9, max_length=256)
    target_chat_id: str = Field(min_length=1, max_length=255)
    label: str | None = Field(default=None, max_length=255)
    account_type: Literal["channel", "group", "bot"] = "channel"


class ScheduledPostCreateRequest(BaseModel):
    platform: Literal["telegram", "instagram", "facebook", "linkedin", "youtube"]
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


def oauth_redirect(provider_key: str) -> str:
    settings = get_settings()
    if provider_key == "google":
        return settings.google_connected_redirect_uri
    if provider_key == "youtube":
        return str(settings.backend_url).rstrip("/") + "/api/connected-apps/youtube/callback"
    if provider_key in {"instagram", "facebook"}:
        return settings.meta_redirect_uri
    if provider_key == "linkedin":
        return settings.linkedin_redirect_uri
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown provider")


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


def validate_state(request: Request, state: str) -> None:
    expected_state = request.cookies.get(INTEGRATION_STATE_COOKIE)
    if not expected_state or expected_state != state:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid OAuth state")


def finish_redirect(response: RedirectResponse) -> RedirectResponse:
    response.delete_cookie(INTEGRATION_STATE_COOKIE, path="/", samesite="lax")
    return response


def dashboard_redirect(tab: str = "connected") -> str:
    return f"{str(get_settings().frontend_url).rstrip('/')}/dashboard?view=settings&tab={tab}"


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


@router.get("/api/connected-apps")
def connected_apps(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    payload = provider_status_payload(db, user)
    db.commit()
    return payload


@router.get("/api/connected-apps/{provider_key}/start")
def start_oauth_connection(
    provider_key: Literal["google", "instagram", "facebook", "linkedin", "youtube"],
    user: User = Depends(get_current_user),
) -> RedirectResponse:
    settings = get_settings()
    state = f"{provider_key}:{user.id}:{secrets.token_urlsafe(24)}"

    if provider_key in {"google", "youtube"}:
        if not settings.google_client_id or not settings.google_client_secret:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Google OAuth is not configured")
        builder = OAuthUrlBuilder(
            auth_uri=settings.google_auth_uri,
            client_id=settings.google_client_id,
            redirect_uri=oauth_redirect(provider_key),
            scopes=google_connected_scopes(provider_key),
            extra_params={"access_type": "offline", "prompt": "consent select_account"},
        )
    elif provider_key in {"instagram", "facebook"}:
        if not settings.meta_app_id or not settings.meta_app_secret:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Meta OAuth is not configured")
        builder = OAuthUrlBuilder(
            auth_uri=settings.meta_oauth_uri,
            client_id=settings.meta_app_id,
            redirect_uri=oauth_redirect(provider_key),
            scopes=meta_oauth_scopes(provider_key),
            extra_params={"auth_type": "rerequest"},
        )
    else:
        if not settings.linkedin_client_id or not settings.linkedin_client_secret:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="LinkedIn OAuth is not configured")
        builder = OAuthUrlBuilder(
            auth_uri=settings.linkedin_auth_uri,
            client_id=settings.linkedin_client_id,
            redirect_uri=oauth_redirect(provider_key),
            scopes=linkedin_oauth_scopes(),
        )

    response = RedirectResponse(builder.get_connect_url(state=state))
    set_state_cookie(response, state)
    return response


@router.get("/api/connected-apps/google/callback")
async def google_connected_callback(
    request: Request,
    code: str = Query(...),
    state: str = Query(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    validate_state(request, state)
    token_data = await exchange_google_code(code=code, redirect_uri=oauth_redirect("google"))
    accounts = await store_google_oauth_accounts(
        db,
        user=user,
        token_data=token_data,
        provider_keys=("google",),
    )
    if not accounts:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Google Workspace scopes were not granted")
    db.commit()
    return finish_redirect(RedirectResponse(dashboard_redirect()))


@router.get("/api/connected-apps/meta/callback")
async def meta_connected_callback(
    request: Request,
    code: str = Query(...),
    state: str = Query(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    validate_state(request, state)
    provider_key = provider_from_state(state, {"instagram", "facebook"}, user.id)
    token_data = await exchange_meta_code(code=code, redirect_uri=oauth_redirect(provider_key))
    token_data = await exchange_meta_long_lived_token(token_data)
    await store_meta_oauth_account(
        db,
        user=user,
        provider_key=provider_key,  # type: ignore[arg-type]
        token_data=token_data,
    )
    db.commit()
    return finish_redirect(RedirectResponse(dashboard_redirect()))


@router.get("/api/connected-apps/linkedin/callback")
async def linkedin_connected_callback(
    request: Request,
    code: str = Query(...),
    state: str = Query(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    validate_state(request, state)
    provider_from_state(state, {"linkedin"}, user.id)
    token_data = await exchange_linkedin_code(code=code, redirect_uri=oauth_redirect("linkedin"))
    await store_linkedin_oauth_account(db, user=user, token_data=token_data)
    db.commit()
    return finish_redirect(RedirectResponse(dashboard_redirect()))


@router.get("/api/connected-apps/youtube/callback")
async def youtube_connected_callback(
    request: Request,
    code: str = Query(...),
    state: str = Query(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    validate_state(request, state)
    token_data = await exchange_google_code(code=code, redirect_uri=oauth_redirect("youtube"))
    accounts = await store_google_oauth_accounts(
        db,
        user=user,
        token_data=token_data,
        provider_keys=("youtube",),
    )
    if not accounts:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="YouTube scopes were not granted")
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
        return {"ok": True, "result": provider_status_payload(db, user)}
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
