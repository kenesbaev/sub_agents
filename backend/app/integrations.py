from __future__ import annotations

import base64
import binascii
import re
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.connected_apps.service import create_scheduled_post, upsert_connected_account, write_activity
from app.core_domain.service import set_task_completion_fields
from app.db.session import get_db
from app.models import InstagramIntegration, SocialPost, Task, TelegramBotIntegration, User
from app.schemas import (
    InstagramConnectRequest,
    InstagramStatus,
    IntegrationsResponse,
    PublishSocialRequest,
    PublishSocialResponse,
    PublishTargetResult,
    PublishTelegramRequest,
    PublishTelegramResponse,
    TelegramBotConnectRequest,
    TelegramBotStatus,
)
from app.security import get_current_user
from app.token_crypto import decrypt_token, encrypt_token

router = APIRouter(tags=["integrations"])

TELEGRAM_CAPTION_LIMIT = 1024
MEDIA_DATA_URL_RE = re.compile(r"^data:(?P<mime>[-\w.+/]+);base64,(?P<data>.+)$", re.DOTALL)
IMAGE_URL_RE = re.compile(r"\.(?:avif|gif|jpe?g|png|webp)(?:[?#].*)?$", re.IGNORECASE)
VIDEO_URL_RE = re.compile(r"\.(?:m4v|mov|mp4|mpeg|mpg|webm)(?:[?#].*)?$", re.IGNORECASE)


def telegram_status(integration: TelegramBotIntegration | None) -> TelegramBotStatus:
    settings = get_settings()
    if not integration:
        if settings.telegram_bot_token and settings.telegram_target_chat_id:
            return TelegramBotStatus(
                connected=True,
                target_chat_id=settings.telegram_target_chat_id,
                bot_username=None,
                updated_at=None,
            )
        return TelegramBotStatus(connected=False)
    return TelegramBotStatus(
        connected=True,
        target_chat_id=integration.target_chat_id,
        bot_username=integration.bot_username,
        updated_at=integration.updated_at,
    )


def instagram_status(integration: InstagramIntegration | None) -> InstagramStatus:
    if not integration:
        return InstagramStatus(connected=False)
    return InstagramStatus(
        connected=True,
        ig_user_id=integration.ig_user_id,
        username=integration.username,
        updated_at=integration.updated_at,
    )


def get_telegram_integration(db: Session, user_id: int) -> TelegramBotIntegration | None:
    return db.scalar(select(TelegramBotIntegration).where(TelegramBotIntegration.user_id == user_id))


def get_instagram_integration(db: Session, user_id: int) -> InstagramIntegration | None:
    return db.scalar(select(InstagramIntegration).where(InstagramIntegration.user_id == user_id))


def telegram_credentials(
    integration: TelegramBotIntegration | None,
) -> tuple[str, str]:
    if integration:
        return decrypt_token(integration.encrypted_bot_token), integration.target_chat_id
    settings = get_settings()
    token = settings.telegram_bot_token.strip()
    target_chat_id = settings.telegram_target_chat_id.strip()
    if token and target_chat_id:
        return token, target_chat_id
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="Telegram Bot is not connected",
    )


def verify_telegram_bot(token: str) -> str | None:
    try:
        with httpx.Client(timeout=15) as client:
            response = client.get(f"https://api.telegram.org/bot{token}/getMe")
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Telegram bot verification failed",
        ) from exc
    try:
        payload = response.json() if response.content else {}
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Telegram bot verification returned an invalid response",
        ) from exc
    if response.status_code >= 400 or not payload.get("ok"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Telegram bot token is invalid",
        )
    result = payload.get("result") or {}
    username = result.get("username")
    return str(username) if username else None


def send_telegram_message(token: str, chat_id: str, text: str) -> dict[str, Any]:
    try:
        with httpx.Client(timeout=20) as client:
            response = client.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={
                    "chat_id": chat_id,
                    "text": text,
                    "disable_web_page_preview": False,
                },
            )
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Telegram publish request failed",
        ) from exc
    try:
        payload = response.json() if response.content else {}
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Telegram publish returned an invalid response",
        ) from exc
    if response.status_code >= 400 or not payload.get("ok"):
        description = str(payload.get("description") or "Telegram rejected the message")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=description[:300])
    result = payload.get("result") or {}
    return result if isinstance(result, dict) else {}


def telegram_media_kind(media_url: str | None, media_type: str | None) -> str:
    media_type = (media_type or "").lower()
    media_url = media_url or ""
    if media_type.startswith("video/") or VIDEO_URL_RE.search(media_url):
        return "video"
    return "photo"


def split_telegram_caption(text: str) -> tuple[str, str]:
    if len(text) <= TELEGRAM_CAPTION_LIMIT:
        return text, ""
    caption = text[:TELEGRAM_CAPTION_LIMIT].rstrip()
    remainder = text[len(caption) :].strip()
    return caption, remainder


def decode_media_data_url(value: str) -> tuple[bytes, str]:
    match = MEDIA_DATA_URL_RE.match(value.strip())
    if not match:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded media is not a valid data URL",
        )
    media_type = match.group("mime")
    try:
        data = base64.b64decode(match.group("data"), validate=True)
    except (binascii.Error, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded media data is invalid",
        ) from exc
    if len(data) > 20 * 1024 * 1024:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded media is too large for publishing",
        )
    return data, media_type


def send_telegram_post(
    token: str,
    chat_id: str,
    text: str,
    *,
    media_url: str | None = None,
    media_data_url: str | None = None,
    media_type: str | None = None,
    media_name: str | None = None,
) -> dict[str, Any]:
    media_url = (media_url or "").strip() or None
    media_data_url = (media_data_url or "").strip() or None
    if not media_url and not media_data_url:
        return send_telegram_message(token, chat_id, text)

    kind = telegram_media_kind(media_url, media_type)
    method = "sendVideo" if kind == "video" else "sendPhoto"
    field = "video" if kind == "video" else "photo"
    caption, remainder = split_telegram_caption(text)
    data: dict[str, Any] = {
        "chat_id": chat_id,
        "caption": caption,
    }
    files: dict[str, tuple[str, bytes, str]] | None = None
    if media_data_url:
        media_bytes, detected_type = decode_media_data_url(media_data_url)
        content_type = media_type or detected_type
        filename = media_name or ("upload.mp4" if kind == "video" else "upload.jpg")
        files = {field: (filename, media_bytes, content_type)}
    else:
        data[field] = media_url

    try:
        with httpx.Client(timeout=60) as client:
            response = client.post(
                f"https://api.telegram.org/bot{token}/{method}",
                data=data,
                files=files,
            )
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Telegram media publish request failed",
        ) from exc
    try:
        payload = response.json() if response.content else {}
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Telegram media publish returned an invalid response",
        ) from exc
    if response.status_code >= 400 or not payload.get("ok"):
        description = str(payload.get("description") or "Telegram rejected the media")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=description[:300])
    result = payload.get("result") if isinstance(payload.get("result"), dict) else {}
    if remainder:
        send_telegram_message(token, chat_id, remainder)
    return result


def graph_api_url(path: str) -> str:
    version = get_settings().meta_graph_api_version.strip().strip("/") or "v23.0"
    clean_path = path.strip("/")
    return f"https://graph.facebook.com/{version}/{clean_path}"


def meta_error_detail(payload: object, fallback: str) -> str:
    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict):
            message = error.get("message")
            if isinstance(message, str) and message.strip():
                return message.strip()[:300]
    return fallback


def verify_instagram_account(access_token: str, ig_user_id: str) -> str | None:
    try:
        with httpx.Client(timeout=20) as client:
            response = client.get(
                graph_api_url(ig_user_id),
                params={"fields": "id,username", "access_token": access_token},
            )
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Instagram verification failed",
        ) from exc
    try:
        payload = response.json() if response.content else {}
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Instagram verification returned an invalid response",
        ) from exc
    if response.status_code >= 400 or not isinstance(payload, dict) or str(payload.get("id") or "") != ig_user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=meta_error_detail(payload, "Instagram access token or IG user ID is invalid"),
        )
    username = payload.get("username")
    return str(username) if username else None


def send_instagram_post(access_token: str, ig_user_id: str, text: str, media_url: str | None) -> dict[str, Any]:
    media = (media_url or "").strip()
    if not media:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Instagram publishing requires a public image or video URL",
        )

    media_lower = media.lower().split("?", 1)[0]
    is_video = media_lower.endswith((".mp4", ".mov"))
    container_payload: dict[str, str] = {
        "access_token": access_token,
        "caption": text,
    }
    if is_video:
        container_payload.update({"media_type": "REELS", "video_url": media})
    else:
        container_payload["image_url"] = media

    try:
        with httpx.Client(timeout=30) as client:
            container_response = client.post(graph_api_url(f"{ig_user_id}/media"), data=container_payload)
            container = container_response.json() if container_response.content else {}
            if container_response.status_code >= 400 or not isinstance(container, dict) or not container.get("id"):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=meta_error_detail(container, "Instagram rejected the media container"),
                )
            publish_response = client.post(
                graph_api_url(f"{ig_user_id}/media_publish"),
                data={"creation_id": str(container["id"]), "access_token": access_token},
            )
            published = publish_response.json() if publish_response.content else {}
    except HTTPException:
        raise
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Instagram publish request failed",
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Instagram publish returned an invalid response",
        ) from exc

    if publish_response.status_code >= 400 or not isinstance(published, dict) or not published.get("id"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=meta_error_detail(published, "Instagram rejected the publish request"),
        )
    return published


def record_social_post(
    db: Session,
    *,
    user_id: int,
    platform: str,
    text: str,
    media_url: str | None,
    source: str | None,
    run_id: str | None,
    status_value: str,
    external_id: str | int | None = None,
    error: str | None = None,
) -> None:
    write_activity(
        db,
        user_id=user_id,
        agent=source,
        service=platform,
        action="publish_post",
        status=status_value,
        external_id=external_id,
        error=error,
        metadata_json={"runId": run_id, "mediaUrl": media_url},
    )
    db.add(
        SocialPost(
            user_id=user_id,
            platform=platform,
            text=text,
            media_url=media_url,
            source=source,
            run_id=run_id,
            status=status_value,
            external_id=str(external_id) if external_id is not None else None,
            error=error,
        )
    )


def find_publish_task(db: Session, user: User, *, task_id: int | None, run_id: str | None) -> Task | None:
    if task_id:
        task = db.get(Task, task_id)
        if task and task.created_by == user.id:
            return task
    if not run_id:
        return None
    try:
        task = db.scalar(
            select(Task)
            .where(Task.created_by == user.id, Task.input_json["runId"].as_string() == run_id)
            .order_by(Task.id.desc())
        )
        if task:
            return task
    except Exception:
        pass
    recent_tasks = db.scalars(select(Task).where(Task.created_by == user.id).order_by(Task.id.desc()).limit(50)).all()
    for task in recent_tasks:
        if isinstance(task.input_json, dict) and task.input_json.get("runId") == run_id:
            return task
    return None


def update_publish_task_status(
    db: Session,
    user: User,
    payload: PublishSocialRequest,
    results: list[PublishTargetResult],
) -> None:
    update_publish_task_from_results(
        db,
        user,
        task_id=payload.task_id,
        run_id=payload.run_id,
        results=results,
    )


def update_publish_task_from_results(
    db: Session,
    user: User,
    *,
    task_id: int | None,
    run_id: str | None,
    results: list[PublishTargetResult],
) -> None:
    task = find_publish_task(db, user, task_id=task_id, run_id=run_id)
    if not task:
        return
    ok = all(result.ok for result in results)
    task.status = "completed" if ok else "failed"
    task.progress = 100 if ok else task.progress
    set_task_completion_fields(task)
    errors = [f"{result.platform}: {result.error}" for result in results if not result.ok and result.error]
    if errors:
        task.error = " | ".join(errors)
    task.result_json = {
        **(task.result_json or {}),
        "publishResults": [result.model_dump() for result in results],
        "published": ok,
    }


def publish_to_platform(
    db: Session,
    user: User,
    *,
    platform: str,
    text: str,
    media_url: str | None,
    media_data_url: str | None,
    media_type: str | None,
    media_name: str | None,
    run_id: str | None,
    source: str | None,
) -> PublishTargetResult:
    try:
        if platform == "telegram":
            token, target_chat_id = telegram_credentials(get_telegram_integration(db, user.id))
            result = send_telegram_post(
                token,
                target_chat_id,
                text,
                media_url=media_url,
                media_data_url=media_data_url,
                media_type=media_type,
                media_name=media_name,
            )
            external_id = result.get("message_id")
        elif platform == "instagram":
            if media_data_url and not media_url:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Instagram requires a public image/video URL; uploaded chat files can publish to Telegram only",
                )
            integration = get_instagram_integration(db, user.id)
            if not integration:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Instagram is not connected",
                )
            access_token = decrypt_token(integration.encrypted_access_token)
            result = send_instagram_post(access_token, integration.ig_user_id, text, media_url)
            external_id = result.get("id")
        else:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported platform")
    except HTTPException as exc:
        detail = str(exc.detail or "Publish failed")[:500]
        record_social_post(
            db,
            user_id=user.id,
            platform=platform,
            text=text,
            media_url=media_url or (f"uploaded:{media_name}" if media_data_url else None),
            source=source,
            run_id=run_id,
            status_value="failed",
            error=detail,
        )
        return PublishTargetResult(platform=platform, ok=False, error=detail)

    record_social_post(
        db,
        user_id=user.id,
        platform=platform,
        text=text,
        media_url=media_url or (f"uploaded:{media_name}" if media_data_url else None),
        source=source,
        run_id=run_id,
        status_value="published",
        external_id=external_id,
    )
    return PublishTargetResult(platform=platform, ok=True, external_id=external_id)


@router.get("/api/integrations", response_model=IntegrationsResponse)
def integrations(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> IntegrationsResponse:
    return IntegrationsResponse(
        telegram_bot=telegram_status(get_telegram_integration(db, user.id)),
        instagram=instagram_status(get_instagram_integration(db, user.id)),
    )


@router.post("/api/integrations/telegram-bot", response_model=IntegrationsResponse)
def connect_telegram_bot(
    payload: TelegramBotConnectRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> IntegrationsResponse:
    token = payload.bot_token.strip()
    target_chat_id = payload.target_chat_id.strip()
    bot_username = verify_telegram_bot(token)
    integration = get_telegram_integration(db, user.id)
    if integration:
        integration.encrypted_bot_token = encrypt_token(token)
        integration.target_chat_id = target_chat_id
        integration.bot_username = bot_username
    else:
        integration = TelegramBotIntegration(
            user_id=user.id,
            encrypted_bot_token=encrypt_token(token),
            target_chat_id=target_chat_id,
            bot_username=bot_username,
        )
        db.add(integration)
    upsert_connected_account(
        db,
        user_id=user.id,
        provider_key="telegram",
        account_identifier=target_chat_id,
        account_label=f"@{bot_username}" if bot_username else target_chat_id,
        account_type="channel",
        access_token=token,
        token_type="bot",
        metadata_json={"botUsername": bot_username},
    )
    db.commit()
    db.refresh(integration)
    return IntegrationsResponse(
        telegram_bot=telegram_status(integration),
        instagram=instagram_status(get_instagram_integration(db, user.id)),
    )


@router.post("/api/integrations/instagram", response_model=IntegrationsResponse)
def connect_instagram(
    payload: InstagramConnectRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> IntegrationsResponse:
    access_token = payload.access_token.strip()
    ig_user_id = payload.ig_user_id.strip()
    username = verify_instagram_account(access_token, ig_user_id)
    integration = get_instagram_integration(db, user.id)
    if integration:
        integration.encrypted_access_token = encrypt_token(access_token)
        integration.ig_user_id = ig_user_id
        integration.username = username
    else:
        integration = InstagramIntegration(
            user_id=user.id,
            encrypted_access_token=encrypt_token(access_token),
            ig_user_id=ig_user_id,
            username=username,
        )
        db.add(integration)
    upsert_connected_account(
        db,
        user_id=user.id,
        provider_key="instagram",
        account_identifier=ig_user_id,
        account_label=f"@{username}" if username else ig_user_id,
        account_type="instagram_business",
        access_token=access_token,
        token_type="bearer",
        metadata_json={"username": username},
    )
    db.commit()
    db.refresh(integration)
    return IntegrationsResponse(
        telegram_bot=telegram_status(get_telegram_integration(db, user.id)),
        instagram=instagram_status(integration),
    )


@router.post("/api/publish/telegram", response_model=PublishTelegramResponse)
def publish_telegram(
    payload: PublishTelegramRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PublishTelegramResponse:
    integration = get_telegram_integration(db, user.id)
    token, target_chat_id = telegram_credentials(integration)
    result = send_telegram_message(token, target_chat_id, payload.text.strip())
    record_social_post(
        db,
        user_id=user.id,
        platform="telegram",
        text=payload.text.strip(),
        media_url=None,
        source=payload.source,
        run_id=payload.run_id,
        status_value="published",
        external_id=result.get("message_id"),
    )
    update_publish_task_from_results(
        db,
        user,
        task_id=payload.task_id,
        run_id=payload.run_id,
        results=[PublishTargetResult(platform="telegram", ok=True, external_id=result.get("message_id"))],
    )
    db.commit()
    chat = result.get("chat") if isinstance(result.get("chat"), dict) else {}
    return PublishTelegramResponse(
        ok=True,
        message_id=result.get("message_id"),
        chat_id=chat.get("id") or target_chat_id,
    )


@router.post("/api/publish/social", response_model=PublishSocialResponse)
def publish_social(
    payload: PublishSocialRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PublishSocialResponse:
    text = payload.text.strip()
    platforms = list(dict.fromkeys(payload.platforms))
    if payload.publish_at:
        results: list[PublishTargetResult] = []
        for platform in platforms:
            post = create_scheduled_post(
                db,
                user_id=user.id,
                platform=platform,
                content=text,
                media_url=payload.media_url,
                media_type=payload.media_type,
                publish_at=payload.publish_at,
                timezone=payload.timezone,
                repeat_rule=payload.repeat_rule,
                source=payload.source,
                run_id=payload.run_id,
            )
            results.append(PublishTargetResult(platform=platform, ok=True, external_id=f"scheduled:{post.id}"))
        update_publish_task_status(db, user, payload, results)
        db.commit()
        return PublishSocialResponse(ok=True, results=results)
    results = [
        publish_to_platform(
            db,
            user,
            platform=platform,
            text=text,
            media_url=payload.media_url,
            media_data_url=payload.media_data_url,
            media_type=payload.media_type,
            media_name=payload.media_name,
            run_id=payload.run_id,
            source=payload.source,
        )
        for platform in platforms
    ]
    update_publish_task_status(db, user, payload, results)
    db.commit()
    return PublishSocialResponse(ok=all(result.ok for result in results), results=results)
