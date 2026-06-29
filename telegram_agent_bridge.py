from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import signal
import threading
import time
from typing import Any

import requests


ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data" / "telegram-agent-bridge"
OFFSETS_FILE = DATA_DIR / "offsets.json"
PENDING_POSTS_FILE = DATA_DIR / "pending_posts.json"
DEFAULT_AGENT_API_URL = "http://127.0.0.1:4173/api/agents/chat"


@dataclass(frozen=True)
class AgentBot:
    key: str
    display_name: str
    username: str
    agent_id: str
    token_env: str


AGENT_BOTS = (
    AgentBot("atlas", "Atlas", "Atlas_REBLY_bot", "coordinator", "TELEGRAM_ATLAS_BOT_TOKEN"),
    AgentBot("ava", "Ava", "Ava_REBLY_bot", "mika", "TELEGRAM_AVA_BOT_TOKEN"),
    AgentBot("scout", "Scout", "Scout_REBLY_bot", "scout", "TELEGRAM_SCOUT_BOT_TOKEN"),
    AgentBot("dex", "Dex", "Dex_REBLY_bot", "dev", "TELEGRAM_DEX_BOT_TOKEN"),
    AgentBot("echo", "Echo", "reblyai_bot", "nova", "TELEGRAM_ECHO_BOT_TOKEN"),
)

PUBLISH_REQUEST_WORDS = {"опубликуй", "отправь", "запости", "выложи", "publish", "send"}
PUBLISH_CONFIRM_WORDS = {"да", "ок", "подтверждаю", "yes"}
PUBLISH_CANCEL_WORDS = {"нет", "отмена", "no"}
PUBLISH_FILLER_WORDS = {"пожалуйста", "плиз", "please", "pls", "можно", "давай", "ну"}
PENDING_POSTS_LOCK = threading.Lock()


def load_local_env(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


load_local_env(ROOT / ".env")
load_local_env(ROOT / "backend" / ".env")


def telegram_call(
    session: requests.Session,
    token: str,
    method: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    response = session.post(
        f"https://api.telegram.org/bot{token}/{method}",
        json=payload or {},
        timeout=35,
    )
    try:
        data = response.json()
    except ValueError as exc:
        raise RuntimeError(f"Telegram {method} returned invalid JSON") from exc
    if not data.get("ok"):
        description = data.get("description") or f"HTTP {response.status_code}"
        raise RuntimeError(f"Telegram {method} failed: {description}")
    result = data.get("result")
    return result if isinstance(result, dict) else {"value": result}


def build_runtime_bots() -> list[tuple[AgentBot, str]]:
    bots: list[tuple[AgentBot, str]] = []
    for bot in AGENT_BOTS:
        token = os.environ.get(bot.token_env, "").strip()
        if token:
            bots.append((bot, token))
    return bots


def bot_key_for_agent_id(agent_id: str) -> str:
    return {
        "coordinator": "atlas",
        "mika": "ava",
        "scout": "scout",
        "dev": "dex",
        "nova": "echo",
    }.get(agent_id, "atlas")


def team_message_delay_seconds() -> float:
    raw = os.environ.get("TELEGRAM_TEAM_MESSAGE_DELAY_SECONDS", "10").strip()
    try:
        return max(0.0, float(raw))
    except ValueError:
        return 10.0


def load_offsets() -> dict[str, int]:
    if not OFFSETS_FILE.exists():
        return {}
    try:
        data = json.loads(OFFSETS_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return {str(key): int(value) for key, value in data.items() if str(value).isdigit()}


def save_offsets(offsets: dict[str, int]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    OFFSETS_FILE.write_text(json.dumps(offsets, indent=2, sort_keys=True), encoding="utf-8")


def load_pending_posts() -> dict[str, Any]:
    if not PENDING_POSTS_FILE.exists():
        return {}
    try:
        data = json.loads(PENDING_POSTS_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def save_pending_posts(data: dict[str, Any]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    PENDING_POSTS_FILE.write_text(json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False), encoding="utf-8")


def chat_store_key(chat_id: int | str) -> str:
    return str(chat_id)


def target_chat_id() -> str:
    return (
        os.environ.get("TELEGRAM_TARGET_CHAT_ID", "").strip()
        or os.environ.get("TELEGRAM_GROUP_CHAT_ID", "").strip()
    )


def command_words(text: str) -> list[str]:
    cleaned = re.sub(r"@[A-Za-z0-9_]+", "", text).strip().lower()
    return re.findall(r"[a-zа-яё]+", cleaned, flags=re.IGNORECASE)


def publish_command_kind(text: str) -> str:
    words = command_words(text)
    if not words or len(words) > 5:
        return ""
    meaningful = [word for word in words if word not in PUBLISH_FILLER_WORDS]
    if not meaningful:
        return ""
    if len(meaningful) <= 2 and meaningful[0] in PUBLISH_CONFIRM_WORDS:
        return "confirm"
    if len(meaningful) <= 2 and meaningful[0] in PUBLISH_CANCEL_WORDS:
        return "cancel"
    if len(meaningful) <= 3 and meaningful[0] in PUBLISH_REQUEST_WORDS:
        return "request"
    return ""


def is_publish_control_text(text: str) -> bool:
    return bool(publish_command_kind(text))


def remember_pending_post(chat_id: int | str, *, text: str, run_id: str = "", source: str = "team") -> None:
    clean_text = text.strip()
    if not clean_text:
        return
    key = chat_store_key(chat_id)
    with PENDING_POSTS_LOCK:
        data = load_pending_posts()
        entry = data.get(key)
        if not isinstance(entry, dict):
            entry = {}
        entry["latest"] = {
            "text": clean_text,
            "runId": run_id,
            "source": source,
            "savedAt": int(time.time()),
        }
        data[key] = entry
        save_pending_posts(data)


def latest_pending_post(chat_id: int | str) -> dict[str, Any] | None:
    key = chat_store_key(chat_id)
    with PENDING_POSTS_LOCK:
        entry = load_pending_posts().get(key)
    if not isinstance(entry, dict):
        return None
    latest = entry.get("latest")
    if not isinstance(latest, dict):
        return None
    text = str(latest.get("text") or "").strip()
    return latest if text else None


def set_publish_confirmation(chat_id: int | str, post: dict[str, Any], target: str) -> None:
    key = chat_store_key(chat_id)
    with PENDING_POSTS_LOCK:
        data = load_pending_posts()
        entry = data.get(key)
        if not isinstance(entry, dict):
            entry = {}
        entry["confirmation"] = {
            "text": str(post.get("text") or "").strip(),
            "targetChatId": target,
            "runId": str(post.get("runId") or ""),
            "requestedAt": int(time.time()),
        }
        data[key] = entry
        save_pending_posts(data)


def pending_publish_confirmation(chat_id: int | str) -> dict[str, Any] | None:
    key = chat_store_key(chat_id)
    with PENDING_POSTS_LOCK:
        entry = load_pending_posts().get(key)
    if not isinstance(entry, dict):
        return None
    confirmation = entry.get("confirmation")
    if not isinstance(confirmation, dict):
        return None
    text = str(confirmation.get("text") or "").strip()
    return confirmation if text else None


def clear_publish_confirmation(chat_id: int | str) -> None:
    key = chat_store_key(chat_id)
    with PENDING_POSTS_LOCK:
        data = load_pending_posts()
        entry = data.get(key)
        if isinstance(entry, dict) and "confirmation" in entry:
            entry.pop("confirmation", None)
            data[key] = entry
            save_pending_posts(data)


def extract_pending_publish(payload: dict[str, Any]) -> dict[str, str] | None:
    pending = payload.get("pendingPublish")
    if not isinstance(pending, dict):
        return None
    text = str(pending.get("text") or "").strip()
    if not text:
        return None
    return {
        "text": text,
        "runId": str(pending.get("runId") or ""),
        "source": str(pending.get("source") or "team"),
    }


def publish_preview(text: str, limit: int = 900) -> str:
    clean = text.strip()
    if len(clean) <= limit:
        return clean
    return clean[:limit].rstrip() + "\n..."


def update_text(update: dict[str, Any]) -> str:
    message = update.get("message") or {}
    text = message.get("text") or message.get("caption") or ""
    return str(text).strip()


def update_chat(update: dict[str, Any]) -> dict[str, Any]:
    return (update.get("message") or {}).get("chat") or {}


def update_sender(update: dict[str, Any]) -> dict[str, Any]:
    return (update.get("message") or {}).get("from") or {}


def update_reply_to_bot(update: dict[str, Any], bot_id: int) -> bool:
    reply = (update.get("message") or {}).get("reply_to_message") or {}
    reply_sender = reply.get("from") or {}
    return int(reply_sender.get("id") or 0) == bot_id


def should_respond(update: dict[str, Any], bot: AgentBot, bot_id: int) -> bool:
    sender = update_sender(update)
    if sender.get("is_bot"):
        return False
    text = update_text(update)
    if not text:
        return False
    chat_type = str(update_chat(update).get("type") or "")
    if chat_type == "private":
        return True
    agent_usernames = [item.username for item in AGENT_BOTS]
    mentions_agent = any(
        re.search(rf"@{re.escape(username)}\b", text, flags=re.IGNORECASE)
        for username in agent_usernames
    )
    username_pattern = rf"@{re.escape(bot.username)}\b"
    if re.search(username_pattern, text, flags=re.IGNORECASE):
        return True
    if update_reply_to_bot(update, bot_id):
        return True
    display_pattern = rf"^\s*{re.escape(bot.display_name)}\b[\s,:;-]*"
    if re.search(display_pattern, text, flags=re.IGNORECASE):
        return True
    return bot.key == "atlas" and not mentions_agent


def clean_message_for_agent(text: str, bot: AgentBot) -> str:
    cleaned = re.sub(rf"@{re.escape(bot.username)}\b", "", text, flags=re.IGNORECASE).strip()
    cleaned = re.sub(
        rf"^\s*/[A-Za-z0-9_]+(?:@{re.escape(bot.username)})?\b",
        "",
        cleaned,
        flags=re.IGNORECASE,
    ).strip()
    cleaned = re.sub(
        rf"^\s*{re.escape(bot.display_name)}\b[\s,:;-]*",
        "",
        cleaned,
        flags=re.IGNORECASE,
    ).strip()
    return cleaned or "Привет. Чем можешь помочь?"


def call_agent_payload(
    session: requests.Session,
    *,
    api_url: str,
    agent_id: str,
    session_id: str,
    chat_id: str,
    message: str,
) -> dict[str, Any]:
    response = session.post(
        api_url,
        json={
            "agentId": agent_id,
            "message": message,
            "history": [],
            "sessionId": session_id,
            "accountId": "telegram",
        },
    )
    try:
        payload = response.json()
    except ValueError as exc:
        raise RuntimeError("Agent API returned invalid JSON") from exc
    if response.status_code >= 400:
        raise RuntimeError(str(payload.get("error") or f"Agent API HTTP {response.status_code}"))
    return payload


def payload_reply_text(payload: dict[str, Any]) -> str:
    reply = str(payload.get("reply") or "").strip()
    if not reply:
        messages = payload.get("messages")
        if isinstance(messages, list):
            for item in reversed(messages):
                if isinstance(item, dict) and str(item.get("text") or "").strip():
                    reply = str(item["text"]).strip()
                    break
    if not reply:
        raise RuntimeError("Agent API returned an empty reply")
    return reply


def call_agent_api(
    session: requests.Session,
    *,
    api_url: str,
    bot: AgentBot,
    chat_id: str,
    message: str,
) -> str:
    payload = call_agent_payload(
        session,
        api_url=api_url,
        agent_id=bot.agent_id,
        session_id=f"telegram:{bot.key}:{chat_id}",
        chat_id=chat_id,
        message=message,
    )
    return payload_reply_text(payload)


def normalized_team_messages(payload: dict[str, Any]) -> list[dict[str, str]]:
    source = payload.get("messages")
    if not isinstance(source, list):
        return [{"from": "coordinator", "text": payload_reply_text(payload), "phase": "final"}]
    result: list[dict[str, str]] = []
    for item in source:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        result.append(
            {
                "from": str(item.get("from") or "coordinator"),
                "text": text,
                "phase": str(item.get("phase") or ""),
            }
        )
    if not result:
        result.append({"from": "coordinator", "text": payload_reply_text(payload), "phase": "final"})
    return result


def split_telegram_text(text: str, limit: int = 3900) -> list[str]:
    parts: list[str] = []
    remaining = text.strip()
    while remaining:
        if len(remaining) <= limit:
            parts.append(remaining)
            break
        split_at = remaining.rfind("\n", 0, limit)
        if split_at < limit // 2:
            split_at = remaining.rfind(" ", 0, limit)
        if split_at < limit // 2:
            split_at = limit
        parts.append(remaining[:split_at].strip())
        remaining = remaining[split_at:].strip()
    return parts or [text[:limit]]


def send_agent_reply(
    session: requests.Session,
    token: str,
    chat_id: int | str,
    text: str,
    *,
    reply_to_message_id: int | None,
) -> None:
    for part in split_telegram_text(text):
        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "text": part,
            "disable_web_page_preview": False,
        }
        if reply_to_message_id:
            payload["reply_parameters"] = {"message_id": reply_to_message_id}
        telegram_call(session, token, "sendMessage", payload)


def handle_publish_command(
    session: requests.Session,
    *,
    token_by_key: dict[str, str],
    chat_id: int | str,
    text: str,
    reply_to_message_id: int | None,
) -> None:
    echo_token = token_by_key.get("echo") or token_by_key.get("atlas")
    if not echo_token:
        return
    kind = publish_command_kind(text)
    if kind == "request":
        post = latest_pending_post(chat_id)
        if not post:
            send_agent_reply(
                session,
                echo_token,
                chat_id,
                "Готового поста пока нет. Сначала попроси команду подготовить пост.",
                reply_to_message_id=reply_to_message_id,
            )
            return
        target = target_chat_id() or str(chat_id)
        set_publish_confirmation(chat_id, post, target)
        post_text = str(post.get("text") or "").strip()
        send_agent_reply(
            session,
            echo_token,
            chat_id,
            (
                f"Опубликовать последний готовый пост в {target}?\n"
                "Ответь: да / нет.\n\n"
                f"Пост:\n{publish_preview(post_text)}"
            ),
            reply_to_message_id=reply_to_message_id,
        )
        return

    if kind == "cancel":
        if pending_publish_confirmation(chat_id):
            clear_publish_confirmation(chat_id)
            message = "Ок, публикацию отменил."
        else:
            message = "Активной публикации на подтверждении нет."
        send_agent_reply(session, echo_token, chat_id, message, reply_to_message_id=reply_to_message_id)
        return

    if kind == "confirm":
        confirmation = pending_publish_confirmation(chat_id)
        if not confirmation:
            send_agent_reply(
                session,
                echo_token,
                chat_id,
                "Нет публикации на подтверждении. Напиши «опубликуй» после готового поста.",
                reply_to_message_id=reply_to_message_id,
            )
            return
        target = str(confirmation.get("targetChatId") or target_chat_id() or chat_id)
        post_text = str(confirmation.get("text") or "").strip()
        try:
            for part in split_telegram_text(post_text):
                telegram_call(
                    session,
                    echo_token,
                    "sendMessage",
                    {
                        "chat_id": target,
                        "text": part,
                        "disable_web_page_preview": False,
                    },
                )
        except Exception as exc:
            send_agent_reply(
                session,
                echo_token,
                chat_id,
                f"Не получилось опубликовать: {str(exc)[:700]}",
                reply_to_message_id=reply_to_message_id,
            )
            return
        clear_publish_confirmation(chat_id)
        send_agent_reply(
            session,
            echo_token,
            chat_id,
            f"Опубликовал в {target}.",
            reply_to_message_id=reply_to_message_id,
        )


def send_team_conversation(
    *,
    api_url: str,
    token_by_key: dict[str, str],
    bot_by_key: dict[str, AgentBot],
    chat_id: int | str,
    message_text: str,
    reply_to_message_id: int | None,
) -> None:
    delay = team_message_delay_seconds()
    with requests.Session() as session:
        try:
            telegram_call(
                session,
                token_by_key["atlas"],
                "sendChatAction",
                {"chat_id": chat_id, "action": "typing"},
            )
            payload = call_agent_payload(
                session,
                api_url=api_url,
                agent_id="all",
                session_id=f"telegram:team:{chat_id}",
                chat_id=str(chat_id),
                message=message_text,
            )
            messages = normalized_team_messages(payload)
            pending_publish = extract_pending_publish(payload)
            if pending_publish:
                remember_pending_post(
                    chat_id,
                    text=pending_publish["text"],
                    run_id=pending_publish.get("runId", ""),
                    source=pending_publish.get("source", "team"),
                )
                print(f"Stored pending Telegram post for chat={chat_id}", flush=True)
        except Exception as exc:
            send_agent_reply(
                session,
                token_by_key["atlas"],
                chat_id,
                f"AI backend error: {str(exc)[:700]}",
                reply_to_message_id=reply_to_message_id,
            )
            print(f"Team AI run failed: {exc}", flush=True)
            return

        for index, item in enumerate(messages):
            if index and delay:
                time.sleep(delay)
            key = bot_key_for_agent_id(item["from"])
            bot = bot_by_key.get(key) or bot_by_key["atlas"]
            token = token_by_key.get(key) or token_by_key["atlas"]
            text = item["text"]
            phase = item["phase"]
            send_agent_reply(
                session,
                token,
                chat_id,
                text,
                reply_to_message_id=reply_to_message_id if index == 0 else None,
            )
            print(f"Team message sent via {bot.display_name}: phase={phase or '-'}", flush=True)


def drop_pending_updates(session: requests.Session, bot: AgentBot, token: str) -> None:
    telegram_call(session, token, "deleteWebhook", {"drop_pending_updates": True})
    print(f"{bot.display_name}: pending Telegram updates dropped", flush=True)


def check_bots(group_chat_id: str) -> None:
    bots = build_runtime_bots()
    if not bots:
        raise SystemExit("No Telegram agent bot tokens configured.")
    with requests.Session() as session:
        for bot, token in bots:
            me = telegram_call(session, token, "getMe")
            bot_user = me
            username = bot_user.get("username")
            bot_id = bot_user.get("id")
            print(f"{bot.display_name}: @{username} -> {bot.agent_id}", flush=True)
            if group_chat_id and bot_id:
                try:
                    member = telegram_call(
                        session,
                        token,
                        "getChatMember",
                        {"chat_id": group_chat_id, "user_id": bot_id},
                    )
                    print(f"  group status: {member.get('status')}", flush=True)
                except RuntimeError as exc:
                    print(f"  group check failed: {exc}", flush=True)


def poll_bot(
    bot: AgentBot,
    token: str,
    *,
    api_url: str,
    token_by_key: dict[str, str],
    bot_by_key: dict[str, AgentBot],
    offsets: dict[str, int],
    offsets_lock: threading.Lock,
    stop_event: threading.Event,
) -> None:
    session = requests.Session()
    me = telegram_call(session, token, "getMe")
    bot_id = int(me.get("id") or 0)
    print(f"{bot.display_name}: listening as @{me.get('username')}", flush=True)
    while not stop_event.is_set():
        with offsets_lock:
            offset = offsets.get(bot.key, 0)
        try:
            updates_payload: dict[str, Any] = {
                "timeout": 20,
                "allowed_updates": ["message"],
            }
            if offset:
                updates_payload["offset"] = offset
            updates_result = telegram_call(
                session,
                token,
                "getUpdates",
                updates_payload,
            )
            updates = updates_result.get("value")
            if not isinstance(updates, list):
                updates = []
            for update in updates:
                update_id = int(update.get("update_id") or 0)
                with offsets_lock:
                    offsets[bot.key] = max(offsets.get(bot.key, 0), update_id + 1)
                    save_offsets(offsets)
                text = update_text(update)
                chat = update_chat(update)
                sender = update_sender(update)
                sender_label = sender.get("username") or sender.get("first_name") or sender.get("id")
                if text:
                    print(
                        f"{bot.display_name}: update chat={chat.get('title') or chat.get('username') or chat.get('id')} "
                        f"from={sender_label} text={text[:80]!r}",
                        flush=True,
                    )
                message = update.get("message") or {}
                chat_id = chat.get("id")
                publish_kind = publish_command_kind(text) if text and not sender.get("is_bot") else ""
                should_handle_publish = publish_kind == "request" or (
                    publish_kind in {"confirm", "cancel"} and chat_id is not None and pending_publish_confirmation(chat_id)
                )
                if should_handle_publish:
                    if bot.key == "echo" and chat_id is not None:
                        telegram_call(session, token, "sendChatAction", {"chat_id": chat_id, "action": "typing"})
                        handle_publish_command(
                            session,
                            token_by_key=token_by_key,
                            chat_id=chat_id,
                            text=text,
                            reply_to_message_id=message.get("message_id"),
                        )
                    continue
                if not should_respond(update, bot, bot_id):
                    continue
                if chat_id is None:
                    continue
                user_text = clean_message_for_agent(update_text(update), bot)
                telegram_call(session, token, "sendChatAction", {"chat_id": chat_id, "action": "typing"})
                try:
                    if bot.key == "atlas" and str(chat.get("type") or "") != "private":
                        team_thread = threading.Thread(
                            target=send_team_conversation,
                            kwargs={
                                "api_url": api_url,
                                "token_by_key": token_by_key,
                                "bot_by_key": bot_by_key,
                                "chat_id": chat_id,
                                "message_text": user_text,
                                "reply_to_message_id": message.get("message_id"),
                            },
                            daemon=True,
                            name=f"team-run-{chat_id}",
                        )
                        team_thread.start()
                        print("Atlas: team run started in background", flush=True)
                        continue
                    reply = call_agent_api(
                        session,
                        api_url=api_url,
                        bot=bot,
                        chat_id=str(chat_id),
                        message=user_text,
                    )
                except Exception as exc:
                    reply = f"{bot.display_name}: AI backend error: {str(exc)[:700]}"
                send_agent_reply(
                    session,
                    token,
                    chat_id,
                    reply,
                    reply_to_message_id=message.get("message_id"),
                )
        except Exception as exc:
            print(f"{bot.display_name}: poll error: {exc}", flush=True)
            time.sleep(5)


def run_bridge(*, api_url: str, drop_pending: bool) -> None:
    bots = build_runtime_bots()
    if not bots:
        raise SystemExit("No Telegram agent bot tokens configured.")
    token_by_key = {bot.key: token for bot, token in bots}
    bot_by_key = {bot.key: bot for bot, _ in bots}
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    offsets = load_offsets()
    offsets_lock = threading.Lock()
    stop_event = threading.Event()

    def stop(*_: object) -> None:
        stop_event.set()

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)

    with requests.Session() as session:
        for bot, token in bots:
            if drop_pending and bot.key not in offsets:
                drop_pending_updates(session, bot, token)

    threads = [
        threading.Thread(
            target=poll_bot,
            args=(bot, token),
            kwargs={
                "api_url": api_url,
                "token_by_key": token_by_key,
                "bot_by_key": bot_by_key,
                "offsets": offsets,
                "offsets_lock": offsets_lock,
                "stop_event": stop_event,
            },
            daemon=True,
            name=f"telegram-{bot.key}",
        )
        for bot, token in bots
    ]
    for thread in threads:
        thread.start()
    while not stop_event.is_set():
        time.sleep(1)
    print("Telegram agent bridge stopped.", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Bind Telegram bots to Rebly AI agents.")
    parser.add_argument(
        "--api-url",
        default=os.environ.get("TELEGRAM_AGENT_API_URL", DEFAULT_AGENT_API_URL),
        help="Agent chat API URL.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Check bot tokens and group membership, then exit.",
    )
    parser.add_argument(
        "--drop-pending",
        action="store_true",
        help="Drop pending Telegram updates for newly configured bots before polling.",
    )
    args = parser.parse_args()
    if args.check:
        check_bots(os.environ.get("TELEGRAM_GROUP_CHAT_ID", "") or os.environ.get("TELEGRAM_TARGET_CHAT_ID", ""))
        return
    run_bridge(api_url=args.api_url, drop_pending=args.drop_pending)


if __name__ == "__main__":
    main()
