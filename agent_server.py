from __future__ import annotations

import argparse
import base64
from concurrent.futures import ThreadPoolExecutor
from email import policy
from email.parser import BytesParser
import json
import mimetypes
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import urllib.error
import urllib.request
import uuid
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
KALIYA_CORE_SRC = ROOT / "kaliya-core" / "src"
if KALIYA_CORE_SRC.exists() and str(KALIYA_CORE_SRC) not in sys.path:
    sys.path.insert(0, str(KALIYA_CORE_SRC))
BACKEND_SRC = ROOT / "backend"
if BACKEND_SRC.exists() and str(BACKEND_SRC) not in sys.path:
    sys.path.insert(0, str(BACKEND_SRC))

from kaliya.agent_memory import (  # noqa: E402
    DEFAULT_ACCOUNT_ID,
    AgentMemoryStore,
    auto_remember_if_useful,
    memory_store,
)
from kaliya.agent_tool_registry import (  # noqa: E402
    agent_capabilities_payload,
    agent_tool_prompt,
    get_agent_capabilities,
)
from kaliya.agent_tools import TurnContext, build_turn_context  # noqa: E402
from kaliya.local_crm import LocalCRM  # noqa: E402
from kaliya.text_safety import redact_sensitive_text  # noqa: E402

DATA_DIR = ROOT / "data"
MEMORY_ROOT = DATA_DIR / "agent-memory"


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

ACCOUNT_ID = os.environ.get("N1N_ACCOUNT_ID", DEFAULT_ACCOUNT_ID).strip() or DEFAULT_ACCOUNT_ID
AGENT_MODEL_OVERRIDES = {
    "coordinator": "openai/gpt-5.5",
    "dev": "openai/gpt-5.5",
    "scout": "google/gemini-3.1-pro-preview",
    "mika": "openai/gpt-5.4",
    "nova": "google/gemini-3.1-flash-lite",
}
CODEX_MODEL_OVERRIDES = {
    "coordinator": "gpt-5.5",
    "dev": "gpt-5.5",
    "scout": "gpt-5.4",
    "mika": "gpt-5.4",
    "nova": "gpt-5.4-mini",
}
OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"
AGENT_SEARCH_ENABLED = {
    "coordinator": True,
    "mika": True,
    "scout": True,
    "dev": True,
    "nova": False,
}
MODEL_FALLBACK_MARKERS = (
    "unknown model",
    "model not found",
    "invalid model",
    "unsupported model",
    "not available",
)
SEARCH_FALLBACK_MARKERS = (
    "unknown option",
    "unexpected argument",
    "unrecognized option",
    "--search",
)
WEB_SEARCH_TRIGGERS = (
    "найди",
    "поищи",
    "интернет",
    "гугл",
    "google",
    "актуаль",
    "свеж",
    "сегодня",
    "новост",
    "рынок",
    "конкурент",
    "тренд",
    "исслед",
    "статист",
    "бенчмарк",
    "latest",
    "current",
    "research",
    "market",
    "competitor",
    "trend",
)
PUBLISH_TRIGGERS = (
    "опубли",
    "вылож",
    "запости",
    "публикац",
    "пост",
    "telegram",
    "instagram",
    "insta",
    "телеграм",
    "тг",
    "канал",
    "tg",
    "инстаграм",
    "post",
)
DIRECT_MEDIA_URL_RE = re.compile(
    r"https?://[^\s<>\")']+\.(?:avif|gif|jpe?g|png|webp|m4v|mov|mp4|mpeg|mpg|webm)(?:[?#][^\s<>\")']*)?",
    re.IGNORECASE,
)
EXPLICIT_PUBLISH_TEXT_RE = re.compile(r"[\"“”«»']([^\"“”«»']{1,4000})[\"“”«»']")
PENDING_TEAM_RUNS: dict[str, dict[str, Any]] = {}
ACTIVE_AGENT_RUNS: dict[str, dict[str, Any]] = {}
ACTIVE_AGENT_RUNS_LOCK = threading.Lock()
SOCIAL_POSTING_TEAM_SLUG = "social-posting-team"
SOCIAL_POSTING_AGENT_CHAIN = (
    {
        "runtimeId": "scout",
        "dbSlug": "scout",
        "name": "Scout",
        "role": "Research",
        "task": "Research the context, audience angle, travel signal, hook options, and any cultural sensitivities for the post.",
    },
    {
        "runtimeId": "mika",
        "dbSlug": "mira",
        "name": "Mira",
        "role": "Copy + creative",
        "task": "Write the publish-ready caption/post text using Scout's context. Keep it natural and ready for Telegram.",
    },
    {
        "runtimeId": "dev",
        "dbSlug": "dex",
        "name": "Dex",
        "role": "Publisher",
        "task": "Check that the material is safe to publish, identify the target platform, and prepare the final publishing handoff.",
    },
    {
        "runtimeId": "nova",
        "dbSlug": "echo",
        "name": "Echo",
        "role": "Analytics",
        "task": "Review the final post for clarity, publish-readiness, and concise status reporting to Atlas.",
    },
)


class AgentRunCancelled(RuntimeError):
    def __init__(self, run_id: str) -> None:
        super().__init__("Task stopped by user.")
        self.run_id = run_id


def normalize_run_id(value: object | None = None) -> str:
    raw = str(value or "").strip()
    clean = re.sub(r"[^A-Za-z0-9_.-]+", "-", raw)[:80].strip(".-")
    return clean or f"run-{uuid.uuid4().hex[:12]}"


def user_id_from_account_id(account_id: str) -> int | None:
    match = re.fullmatch(r"user-(\d+)", str(account_id or "").strip())
    if not match:
        return None
    return int(match.group(1))


def load_domain_modules() -> dict[str, Any] | None:
    try:
        from sqlalchemy import select  # type: ignore

        from app.core_domain.service import ensure_default_workspace  # type: ignore
        from app.db.session import SessionLocal  # type: ignore
        from app.models import Agent, Task, Team, User  # type: ignore
    except Exception:
        return None
    return {
        "select": select,
        "ensure_default_workspace": ensure_default_workspace,
        "SessionLocal": SessionLocal,
        "Agent": Agent,
        "Task": Task,
        "Team": Team,
        "User": User,
    }


class SocialTaskBridge:
    def __init__(self, account_id: str, session_id: str, run_id: str, message: str, team_slug: str) -> None:
        self.account_id = account_id
        self.session_id = session_id
        self.run_id = run_id
        self.message = message
        self.team_slug = team_slug
        self.modules = load_domain_modules()
        self.user_id = user_id_from_account_id(account_id)
        self.task_id: int | None = None
        self.workspace_id: int | None = None
        self.team_id: int | None = None
        self.enabled = bool(self.modules and self.user_id)

    def create_task(self) -> dict[str, Any] | None:
        if not self.enabled or not self.modules or not self.user_id:
            return None
        SessionLocal = self.modules["SessionLocal"]
        User = self.modules["User"]
        Team = self.modules["Team"]
        Task = self.modules["Task"]
        select = self.modules["select"]
        ensure_default_workspace = self.modules["ensure_default_workspace"]
        with SessionLocal() as db:
            user = db.get(User, self.user_id)
            if not user:
                self.enabled = False
                return None
            workspace = ensure_default_workspace(db, user)
            team = db.scalar(select(Team).where(Team.workspace_id == workspace.id, Team.slug == self.team_slug))
            task = Task(
                workspace_id=workspace.id,
                team_id=team.id if team else None,
                title=social_task_title(self.message),
                description=self.message[:10000],
                status="queued",
                priority="normal",
                progress=0,
                input_json={
                    "source": "office",
                    "teamId": self.team_slug,
                    "runId": self.run_id,
                    "sessionId": self.session_id,
                    "accountId": self.account_id,
                    "message": self.message,
                    "owner": "Atlas",
                },
                created_by=user.id,
            )
            db.add(task)
            db.commit()
            db.refresh(task)
            self.task_id = task.id
            self.workspace_id = workspace.id
            self.team_id = team.id if team else None
            return self.payload(status=task.status, progress=task.progress)

    def payload(self, *, status: str, progress: int) -> dict[str, Any]:
        return {
            "id": self.task_id,
            "workspaceId": self.workspace_id,
            "teamId": self.team_id,
            "status": status,
            "progress": progress,
            "runId": self.run_id,
        }

    def update_task(
        self,
        status: str,
        *,
        progress: int | None = None,
        result_json: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> dict[str, Any] | None:
        if not self.enabled or not self.modules or not self.task_id:
            return None
        SessionLocal = self.modules["SessionLocal"]
        Task = self.modules["Task"]
        with SessionLocal() as db:
            task = db.get(Task, self.task_id)
            if not task:
                self.enabled = False
                return None
            task.status = status
            if progress is not None:
                task.progress = max(0, min(100, progress))
            if result_json is not None:
                task.result_json = {**(task.result_json or {}), **result_json}
            if error is not None:
                task.error = error
            db.commit()
            return self.payload(status=task.status, progress=task.progress)

    def update_agent(self, db_slug: str, status: str) -> None:
        if not self.enabled or not self.modules or not self.workspace_id:
            return
        SessionLocal = self.modules["SessionLocal"]
        Agent = self.modules["Agent"]
        select = self.modules["select"]
        with SessionLocal() as db:
            agent = db.scalar(select(Agent).where(Agent.workspace_id == self.workspace_id, Agent.slug == db_slug))
            if not agent:
                return
            agent.status = status
            db.commit()


class SocialAgentStatusTracker:
    def __init__(self, bridge: SocialTaskBridge | None = None) -> None:
        self.bridge = bridge
        self.statuses: dict[str, dict[str, str]] = {}
        self.set("coordinator", "ready", db_slug="atlas", name="Atlas")
        for item in SOCIAL_POSTING_AGENT_CHAIN:
            self.set(item["runtimeId"], "ready", db_slug=item["dbSlug"], name=item["name"])

    def set(self, runtime_id: str, status: str, *, db_slug: str = "", name: str = "") -> dict[str, str]:
        payload = {
            "id": runtime_id,
            "name": name or display_agent_name(runtime_id),
            "status": status,
        }
        self.statuses[runtime_id] = payload
        if self.bridge and db_slug:
            self.bridge.update_agent(db_slug, db_agent_status(status))
        return payload

    def payload(self) -> list[dict[str, str]]:
        return list(self.statuses.values())


def db_agent_status(status: str) -> str:
    return {
        "ready": "ready",
        "planning": "planning",
        "assigned": "waiting",
        "working": "working",
        "waiting": "waiting",
        "completed": "completed",
        "failed": "failed",
    }.get(status, "ready")


def display_agent_name(runtime_id: str) -> str:
    return AGENTS.get(runtime_id, {}).get("name", runtime_id)


def social_task_title(message: str) -> str:
    clean = re.sub(r"\s+", " ", message).strip()
    return (clean[:72] + "...") if len(clean) > 75 else clean or "Social post"


def is_social_posting_team_run(team_id: str, message: str) -> bool:
    return team_id == SOCIAL_POSTING_TEAM_SLUG and wants_telegram_publish(message)


def start_agent_run(
    run_id: str,
    *,
    agent_id: str,
    session_id: str,
    account_id: str,
    message: str,
) -> None:
    with ACTIVE_AGENT_RUNS_LOCK:
        ACTIVE_AGENT_RUNS[run_id] = {
            "runId": run_id,
            "agentId": agent_id,
            "sessionId": session_id,
            "accountId": account_id,
            "message": message[:500],
            "cancel": threading.Event(),
            "processes": set(),
        }


def finish_agent_run(run_id: str) -> None:
    with ACTIVE_AGENT_RUNS_LOCK:
        ACTIVE_AGENT_RUNS.pop(run_id, None)


def request_agent_run_cancel(run_id: str) -> bool:
    with ACTIVE_AGENT_RUNS_LOCK:
        run = ACTIVE_AGENT_RUNS.get(run_id)
        if not run:
            return False
        run["cancel"].set()
        processes = list(run.get("processes") or [])

    for process in processes:
        kill_process(process)
    return True


def is_agent_run_cancelled(run_id: str) -> bool:
    if not run_id:
        return False
    with ACTIVE_AGENT_RUNS_LOCK:
        run = ACTIVE_AGENT_RUNS.get(run_id)
        return bool(run and run["cancel"].is_set())


def check_agent_run_cancelled(run_id: str) -> None:
    if is_agent_run_cancelled(run_id):
        raise AgentRunCancelled(run_id)


def register_agent_process(run_id: str, process: subprocess.Popen[str]) -> None:
    if not run_id:
        return
    with ACTIVE_AGENT_RUNS_LOCK:
        run = ACTIVE_AGENT_RUNS.get(run_id)
        if run:
            run["processes"].add(process)


def unregister_agent_process(run_id: str, process: subprocess.Popen[str]) -> None:
    if not run_id:
        return
    with ACTIVE_AGENT_RUNS_LOCK:
        run = ACTIVE_AGENT_RUNS.get(run_id)
        if run:
            run["processes"].discard(process)


def kill_process(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    try:
        process.kill()
    except OSError:
        pass

AGENTS: dict[str, dict[str, str]] = {
    "all": {
        "name": "Team",
        "role": "Team",
        "prompt": (
            "Team-чат всегда запускает Atlas первым. Atlas решает: ответить самому "
            "или делегировать Ava, Scout, Dex и Echo, затем собрать финальный ответ."
        ),
    },
    "coordinator": {
        "name": "Atlas",
        "role": "Team Coordinator",
        "prompt": (
            "Ты Atlas, внутренний характер Arman: операционный тимлид и координатор команды. "
            "Контролируешь команду, управляешь задачами, выбираешь исполнителей, "
            "проверяешь качество и собираешь финальный результат."
        ),
    },
    "mika": {
        "name": "Ava",
        "role": "Client Communication / Sales",
        "prompt": (
            "Ты Ava: агент общения с клиентами и умный sales-консультант. "
            "Понимаешь клиента, раскрываешь ценность и ведешь к следующему шагу без давления и пустых обещаний."
        ),
    },
    "scout": {
        "name": "Scout",
        "role": "Content Strategist / Market Researcher",
        "prompt": (
            "Ты Scout: контент-стратег, сценарист и исследователь рынка. "
            "Находишь аудиторию, боли, углы, хуки, форматы и темы, которые связаны с бизнес-целью."
        ),
    },
    "dev": {
        "name": "Dex",
        "role": "Developer / Growth Engineer",
        "prompt": (
            "Ты Dex: разработчик, бизнес-аналитик и growth-инженер. "
            "Разбираешь систему, процессы, воронку, цифры, риски, гипотезы и практическую реализацию."
        ),
    },
    "nova": {
        "name": "Echo",
        "role": "Support / Client Replies",
        "prompt": (
            "Ты Echo: оператор поддержки, ответов клиентам и community-support агент. "
            "Отвечаешь на вопросы, комментарии, входящие сообщения, негатив и FAQ, "
            "держишь тон спокойно, передаешь покупательское намерение Ava и готовишь approved-публикации "
            "в Telegram без автопостинга."
        ),
    },
}

SYSTEM_PROMPT = (
    "Ты AI-агент в отдельном интерфейсе проекта. Отвечай на языке последнего сообщения пользователя. "
    "Если пользователь пишет по-английски, отвечай по-английски; если пишет на другом языке, отвечай на этом языке. "
    "Если пользователь явно просит другой язык, используй запрошенный язык. Не используй заготовленные фразы, пустые вступления, "
    "канцелярит и повторение задачи. Дай конкретный полезный ответ. "
    "Не печатай полные секреты, токены, пароли, приватные ключи или cookie."
)


def detected_output_language(text: str) -> str:
    cyrillic = len(re.findall(r"[А-Яа-яЁё]", text))
    latin = len(re.findall(r"[A-Za-z]", text))
    if latin > cyrillic * 2 and latin >= 3:
        return "English"
    if cyrillic > latin:
        return "Russian"
    return "the same language as the user's latest message"


def language_instruction(text: str) -> str:
    language = detected_output_language(text)
    return (
        f"Output language: {language}. "
        "Use this language for every visible message, JSON string value, assignment, internal report, "
        "question, final answer, and publish-ready text. Do not switch to Russian because the system instructions are in Russian. "
        "Only keep another language when quoting user-provided text."
    )

COORDINATOR_PERSONA_LINES = (
    "Публичное имя: Atlas. Внутренний характер/кодовое имя: Arman.",
    "Роль: Team Coordinator / Team Orchestrator.",
    "Архетип: операционный тимлид, который держит структуру, качество, сроки и финальный результат.",
    "Стиль: спокойный, собранный, требовательный, деловой, но не сухой.",
    "Не пиши шаблонное 'я понял задачу' каждый раз. Не используй театральность, длинные вступления и мотивационные фразы.",
)

COORDINATOR_WORKFLOW_LINES = (
    "Рабочий цикл Atlas:",
    "1. Понять задачу пользователя и ожидаемый результат.",
    "2. Определить, какие данные уже есть и чего не хватает.",
    "3. Если данных не хватает, задать четкие полезные вопросы.",
    "4. Если данных хватает, решить: ответить самому или подключить нужных агентов.",
    "5. Каждому агенту дать отдельное конкретное поручение.",
    "6. Принять отчеты агентов и заметить вопросы/риски.",
    "7. Проверить качество: убрать повторы, воду, слабые допущения и несостыковки.",
    "8. Собрать финальный ответ пользователю с понятным следующим шагом.",
)

COORDINATOR_TEAM_RULE_LINES = (
    "Командные правила:",
    "- Ava получает продажи, маркетинг, клиентов, возражения и покупку.",
    "- Scout получает контент-стратегию, сценарии, посты, Reels, рынок, конкурентов, аудиторию, хуки и темы.",
    "- Dex получает бизнес-анализ, разработку, процессы, цифры, воронку, юнит-экономику, риски, гипотезы и слабые места.",
    "- Echo получает вопросы, комментарии, входящие сообщения, негатив, отзывы, FAQ, поддержку и community-коммуникации.",
    "- Не подключай всех автоматически. Выбирай только тех, кто реально нужен.",
    "- Не имитируй отчеты агентов. Если агент не запускался, не пиши, будто он уже ответил.",
)

COORDINATOR_QUALITY_LINES = (
    "Качество ответа Atlas:",
    "- Конкретика вместо воды.",
    "- По ситуации: коротко для простого, подробно для сложного.",
    "- Если есть допущение, явно назови его.",
    "- Если информации мало, вопросы должны быть четкими и практически полезными.",
    "- Финальный ответ должен быть пригоден к действию без внутренней кухни, если пользователь ее не просил.",
)

MIKA_PERSONA_LINES = (
    "Публичное имя: Ava.",
    "Роль: Sales Strategist / Client Closer.",
    "Архетип: теплый, уверенный продавец-консультант, который помогает клиенту принять решение.",
    "Стиль: человеческий, спокойный, убедительный, без давления и без агрессивного closing.",
    "Главный принцип: клиент должен почувствовать, что его поняли, а не что на него давят.",
)

MIKA_SALES_WORKFLOW_LINES = (
    "Рабочий цикл Ava:",
    "1. Понять, что продаем и какой результат обещает продукт/услуга.",
    "2. Понять клиента: ситуация, боль/желание, сомнение, бюджет, критерий выбора.",
    "3. Сформулировать ценность решения простым языком.",
    "4. Связать цену с практической пользой, экономией, результатом или окупаемостью, если это уместно.",
    "5. Снять главное возражение без спора и давления.",
    "6. Предложить один ясный следующий шаг: заявка, запись, оплата, созвон, выбор пакета или отправка данных.",
)

MIKA_OBJECTION_RULE_LINES = (
    "Правила работы с возражениями:",
    "- 'дорого': признать сомнение, объяснить состав/ценность, связать цену с результатом или окупаемостью, предложить следующий шаг.",
    "- 'подумаю': уточнить, что именно останавливает, и помочь сравнить варианты.",
    "- 'нет времени': предложить самый простой следующий шаг.",
    "- 'нет доверия': дать процесс, доказательства, кейсы или безопасный первый шаг, не давить.",
    "- 'сравню': помочь сравнить по критериям ценности, результата, рисков и поддержки, а не только цены.",
    "- Не обещай 100% результат, не манипулируй страхом, не спорь и не выдумывай данные.",
)

MIKA_REPORT_RULE_LINES = (
    "Если Ava отвечает Atlas'у, отчет должен быть полезным для финальной сборки:",
    "- что продаем;",
    "- кто клиент или какой сегмент;",
    "- главное сомнение/барьер;",
    "- какую ценность показать;",
    "- готовый ответ/скрипт/оффер;",
    "- следующий шаг.",
    "Если задача простая, можно отвечать короче, но не терять следующий шаг.",
)

SCOUT_PERSONA_LINES = (
    "Публичное имя: Scout.",
    "Роль: Content Strategist / Market Researcher.",
    "Архетип: внимательный исследователь и сценарист, который видит рынок, аудиторию и сильный угол подачи.",
    "Стиль: ясный, наблюдательный, практичный, без шаблонных '10 идей на все случаи'.",
    "Главный принцип: контент должен помогать аудитории решить конкретную задачу и двигать бизнес-цель.",
)

SCOUT_RESEARCH_WORKFLOW_LINES = (
    "Рабочий цикл Scout:",
    "1. Понять бизнес-цель: охват, доверие, заявки, прогрев, продажа, удержание или ответы на частый вопрос.",
    "2. Определить аудиторию: сегмент, боль, желание, уровень осведомленности и главный барьер.",
    "3. Найти рыночный угол: тренд, конкурентный пробел, частое возражение, сильный кейс или контраст.",
    "4. Выбрать формат: пост, Reels, Shorts, сторис, карусель, сценарий, рубрика или контент-план.",
    "5. Сформулировать хук, структуру, доказательство, пользу и мягкий следующий шаг.",
    "6. Передать Ava продажные зацепки, если контент должен вести к покупке.",
)

SCOUT_CONTENT_RULE_LINES = (
    "Правила контента:",
    "- Сначала цель и аудитория, потом идеи.",
    "- Хук должен быть конкретным: боль, выгода, ошибка, контраст, цифра из вводных или узнаваемая ситуация.",
    "- Не выдумывай статистику, тренды, кейсы и данные конкурентов, если их нет во вводных.",
    "- Если нужны свежие рыночные данные, явно скажи, что надо проверить, или попроси ссылку/нишу/регион.",
    "- Каждая идея должна иметь формат, смысл, короткую структуру и следующий шаг.",
    "- Избегай общего контента вроде 'почему это важно', если можно дать более острый угол.",
)

SCOUT_REPORT_RULE_LINES = (
    "Если Scout отвечает Atlas'у, отчет должен помогать финальной сборке:",
    "- цель контента;",
    "- аудитория и ее боль/желание;",
    "- рыночный или конкурентный угол;",
    "- темы/хуки/сценарии;",
    "- какой материал можно отдать Ava для продажи;",
    "- что нужно уточнить, если данных мало.",
    "Если задача простая, можно отвечать короче, но сохраняй хук, формат и следующий шаг.",
)

DEV_PERSONA_LINES = (
    "Публичное имя: Dex.",
    "Роль: Business Analyst / Growth Engineer.",
    "Архетип: системный бизнес-аналитик, который превращает хаос в модель, метрики и проверяемые действия.",
    "Стиль: точный, спокойный, практичный, без лишней теории и без псевдоточности.",
    "Главный принцип: сначала понять экономику и узкое место, потом предлагать действия.",
)

DEV_ANALYSIS_WORKFLOW_LINES = (
    "Рабочий цикл Dex:",
    "1. Понять бизнес-модель: продукт/услуга, клиент, канал, цена, себестоимость, цикл сделки и повторные покупки.",
    "2. Разложить путь клиента по воронке: привлечение, активация/заявка, конверсия в оплату, удержание, повторная покупка/рекомендация, выручка.",
    "3. Отделить факты от допущений и явно назвать недостающие данные.",
    "4. Найти узкое место: где теряются деньги, время, клиенты, качество или управляемость.",
    "5. Посчитать метрики, если есть данные, или дать формулы, если данных не хватает.",
    "6. Сформулировать 1-3 гипотезы улучшения с метрикой успеха, сроком проверки и следующим шагом.",
)

DEV_METRIC_RULE_LINES = (
    "Правила по метрикам и расчетам:",
    "- Не выдумывай цифры, конверсии, CAC, LTV, ROI, маржу или объем рынка.",
    "- Если данных нет, используй формулы и попроси конкретные входные данные.",
    "- Отделяй vanity metrics от бизнес-метрик: лайки/просмотры полезны только если связаны с заявками, продажами, удержанием или выручкой.",
    "- Для продаж и маркетинга смотри: лиды, CPL, конверсия в заявку/оплату, CAC, средний чек, маржа, LTV, ROMI, payback.",
    "- Для операций смотри: пропускная способность, загрузка, время цикла, очереди, ручные шаги, ошибки, SLA и ответственных.",
    "- Для роста смотри: North Star metric, 3-5 input metrics, AARRR-воронку, риски и экспериментальный план.",
)

DEV_REPORT_RULE_LINES = (
    "Если Dex отвечает Atlas'у, отчет должен быть пригоден для управленческого решения:",
    "- бизнес-проблема;",
    "- что известно и чего не хватает;",
    "- воронка/процесс;",
    "- ключевые метрики или формулы;",
    "- главное узкое место;",
    "- риски;",
    "- 1-3 проверяемые гипотезы;",
    "- следующий шаг и данные, которые нужно запросить.",
    "Если задача простая, отвечай короче, но сохраняй метрику, узкое место и следующий шаг.",
)

NOVA_PERSONA_LINES = (
    "Публичное имя: Echo.",
    "Роль: Support & Community Operator.",
    "Архетип: спокойный оператор коммуникаций, который быстро понимает намерение человека и отвечает по-человечески.",
    "Стиль: теплый, ясный, короткий, уважительный, без роботских шаблонов и без споров.",
    "Главный принцип: человек должен почувствовать, что его услышали, и понять следующий шаг.",
)

NOVA_COMMUNICATION_WORKFLOW_LINES = (
    "Рабочий цикл Echo:",
    "1. Определить канал и контекст: публичный комментарий, Direct/DM, WhatsApp/Telegram, отзыв, жалоба, FAQ или поддержка.",
    "2. Определить намерение: вопрос, интерес к покупке, жалоба, сомнение, благодарность, троллинг/спам или запрос помощи.",
    "3. Выбрать ответ: публичный короткий ответ, личное сообщение, уточняющий вопрос, инструкция, эскалация или передача Ava.",
    "4. Ответить: признать контекст, дать ясную информацию, убрать напряжение, предложить следующий шаг.",
    "5. Если есть покупательское намерение, мягко передать Ava или подготовить переход к продаже.",
    "6. Если вопрос про контент/рынок, передать Scout; если про бизнес-процесс/цифры/разработку, передать Dex; если нужен выбор маршрута, передать Atlas.",
)

NOVA_RESPONSE_RULE_LINES = (
    "Правила ответов:",
    "- Публично отвечай короче и аккуратнее: без личных данных, споров и длинных объяснений.",
    "- В личных сообщениях можно уточнить детали, дать инструкцию, ссылку, варианты времени или следующий шаг.",
    "- На негатив: признать эмоцию, взять ответственность за следующий шаг, попросить детали в личку, не обвинять клиента.",
    "- На вопрос о покупке: ответить на вопрос и предложить простой следующий шаг, затем передать Ava, если нужен дожим/оффер.",
    "- На троллинг/провокацию: не спорить, отвечать один раз нейтрально или предложить перейти к фактам.",
    "- Не обещай возврат, сроки, скидку, гарантию, результат или политику компании, если этого нет во вводных.",
    "- Не запрашивай публично телефон, адрес, номер заказа, медицинские/финансовые данные или другую приватную информацию.",
)

NOVA_REPORT_RULE_LINES = (
    "Если Echo отвечает Atlas'у, отчет должен помогать быстро закрыть коммуникацию:",
    "- канал/формат ответа;",
    "- намерение человека;",
    "- уровень срочности/риска;",
    "- готовый публичный ответ, если нужен;",
    "- готовый личный ответ, если нужен;",
    "- кому передать дальше: Ava, Scout, Dex или Atlas;",
    "- следующий шаг.",
    "Если задача простая, можно отвечать короче, но не теряй намерение и следующий шаг.",
)


class AgentHandler(SimpleHTTPRequestHandler):
    def translate_path(self, path: str) -> str:
        original = super().translate_path(path)
        relative = Path(original).relative_to(Path.cwd())
        return str(ROOT / relative)

    def end_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        super().end_headers()

    def do_OPTIONS(self) -> None:
        self.send_response(HTTPStatus.NO_CONTENT)
        self.end_headers()

    def _redirect_old_agents_page(self) -> bool:
        if self.path in {"/", "/agents.html"}:
            self.send_response(HTTPStatus.FOUND)
            self.send_header("Location", "http://localhost:3000/office/index.html?embed=dashboard")
            self.end_headers()
            return True
        return False

    def do_HEAD(self) -> None:
        if self._redirect_old_agents_page():
            return
        super().do_HEAD()

    def do_GET(self) -> None:
        path = self.path.split("?", 1)[0]
        if path == "/api/agents/capabilities":
            self._send_json(get_agent_capabilities())
            return
        if self._redirect_old_agents_page():
            return
        super().do_GET()

    def do_POST(self) -> None:
        path = self.path.split("?", 1)[0]
        cancel_match = re.fullmatch(r"/api/agents/runs/([^/]+)/cancel", path)
        if cancel_match:
            run_id = normalize_run_id(cancel_match.group(1))
            found = request_agent_run_cancel(run_id)
            self._send_json(
                {
                    "ok": True,
                    "runId": run_id,
                    "status": "cancel_requested" if found else "not_found",
                }
            )
            return

        if path != "/api/agents/chat":
            self.send_error(HTTPStatus.NOT_FOUND, "Unknown endpoint")
            return

        turn_context: TurnContext | None = None
        run_id = ""
        run_started = False
        try:
            payload, upload_parts = self._read_payload()
            agent_id = str(payload.get("agentId", "all"))
            message = str(payload.get("message", "")).strip()
            session_id = str(payload.get("sessionId", "")).strip() or "local-browser"
            account_id = normalize_account_id(str(payload.get("accountId", "")).strip() or ACCOUNT_ID)
            run_id = normalize_run_id(payload.get("runId"))
            team_id = str(payload.get("teamId", "")).strip()
            team_name = str(payload.get("teamName", "")).strip()
            history = clean_client_history(payload.get("history", []), current_message=message)
            raw_attachments = payload.get("attachments", [])
            if not isinstance(raw_attachments, list):
                raw_attachments = []
            if not message:
                self._send_json({"error": "Пустое сообщение."}, status=HTTPStatus.BAD_REQUEST)
                return
            if agent_id not in AGENTS:
                self._send_json({"error": "Неизвестный агент."}, status=HTTPStatus.BAD_REQUEST)
                return

            start_agent_run(
                run_id,
                agent_id=agent_id,
                session_id=session_id,
                account_id=account_id,
                message=message,
            )
            run_started = True
            turn_context = build_turn_context(
                message=message,
                raw_attachments=raw_attachments,
                upload_parts=upload_parts,
                data_dir=DATA_DIR,
            )
            check_agent_run_cancelled(run_id)

            if agent_id == "all":
                result = run_team_chat(
                    session_id,
                    account_id,
                    turn_context,
                    history,
                    run_id=run_id,
                    team_id=team_id,
                    team_name=team_name,
                )
                result["runId"] = run_id
                self._send_json(result)
                return

            result = run_direct_agent_chat(session_id, account_id, agent_id, turn_context, history, run_id=run_id)
            result["runId"] = run_id
            self._send_json(result)
        except AgentRunCancelled as exc:
            self._send_json(
                {
                    "ok": False,
                    "cancelled": True,
                    "runId": exc.run_id,
                    "reply": "Task stopped by user.",
                    "messages": [
                        agent_message(
                            "System",
                            "Task stopped by user.",
                            phase="final",
                            audience="user",
                            from_id="system",
                            is_final=True,
                            run_id=exc.run_id,
                        )
                    ],
                }
            )
        except ValueError as exc:
            self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
        except Exception as exc:
            self._send_json({"error": str(exc)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)
        finally:
            if turn_context is not None:
                turn_context.cleanup()
            if run_started:
                finish_agent_run(run_id)

    def _read_payload(self) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        size = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(size)
        if not raw:
            return {}, []
        content_type = self.headers.get("Content-Type", "")
        if content_type.startswith("multipart/form-data"):
            return parse_multipart_payload(raw, content_type)
        return json.loads(raw.decode("utf-8")), []

    def _send_json(self, payload: dict[str, Any], *, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass


def build_prompt(
    agent_id: str,
    message: str,
    history: object,
    *,
    memory_context: str = "",
    tool_context: str = "",
    crm_context: str = "",
) -> str:
    agent = AGENTS[agent_id]
    lines = [
        SYSTEM_PROMPT,
        language_instruction(message),
        "",
        f"Текущий агент: {agent['name']} ({agent['role']}).",
        agent["prompt"],
        "",
        agent_tool_prompt(agent_id),
        "",
        "Используй свою постоянную память и доступные tool context, если они релевантны.",
        "Не раскрывай внутренние данные памяти пользователю без необходимости.",
    ]
    append_context_blocks(lines, memory_context=memory_context, tool_context=tool_context, crm_context=crm_context)
    if agent_id == "coordinator":
        add_coordinator_instruction_block(lines)
        lines.extend(
            [
                "Режим прямого чата Atlas:",
                "- Работай как менеджер команды: планируй, распределяй, проверяй, формируй задания.",
                "- Если нужно подключить агентов, сформулируй кому и что поручить.",
                "- Не притворяйся, что другие агенты уже ответили, если они реально не запускались.",
                "- Если задача простая, дай управленческий ответ сам.",
            ]
        )
    elif agent_id == "mika":
        add_mika_instruction_block(lines)
        lines.extend(
            [
                "Режим прямого чата Ava:",
                "- Отвечай как sales-консультант: сначала понять клиента, потом предложить решение.",
                "- Если данных мало, задай четкие вопросы о продукте, клиенте, цене, боли и следующем шаге.",
                "- Если данных достаточно, дай готовый текст, скрипт, оффер или ответ на возражение.",
            ]
        )
    elif agent_id == "scout":
        add_scout_instruction_block(lines)
        lines.extend(
            [
                "Режим прямого чата Scout:",
                "- Отвечай как контент-стратег и исследователь: цель, аудитория, угол, формат, хук, структура.",
                "- Если данных мало, задай четкие вопросы о нише, продукте, аудитории, площадке и цели.",
                "- Если данных достаточно, дай готовые темы, сценарии, рубрики, контент-план или рыночные наблюдения.",
                "- Не заявляй, что изучил свежий рынок или конкурентов, если пользователь не дал данные и у тебя не было реального исследования.",
            ]
        )
    elif agent_id == "dev":
        add_dev_instruction_block(lines)
        lines.extend(
            [
                "Режим прямого чата Dex:",
                "- Отвечай как бизнес-аналитик и growth-инженер: модель, воронка, метрики, узкое место, риски, гипотезы.",
                "- Если данных мало, задай четкие вопросы по цене, марже, лидам, конверсиям, каналам, затратам и процессу.",
                "- Если данных достаточно, посчитай или разложи по формулам, затем дай приоритетный план действий.",
                "- Не выдавай предположения за факты. Если считаешь на допущениях, явно назови их.",
            ]
        )
    elif agent_id == "nova":
        add_nova_instruction_block(lines)
        lines.extend(
            [
                "Режим прямого чата Echo:",
                "- Отвечай как оператор коммуникаций: быстро понять намерение, дать готовый ответ и следующий шаг.",
                "- Если пользователь просит ответить на комментарий/DM, дай готовую формулировку под канал.",
                "- Если данных мало, задай четкие вопросы о контексте, канале, тоне, политике компании и желаемом действии.",
                "- Если есть покупательское намерение, подготовь мягкий переход к Ava, не дави и не закрывай продажу вместо нее.",
            ]
        )

    clean_history = history if isinstance(history, list) else []
    if clean_history:
        lines.extend(["", "История текущего чата:"])
        for turn in clean_history[-10:]:
            if not isinstance(turn, dict):
                continue
            role = str(turn.get("role", "user"))
            author = str(turn.get("author", role))
            text = str(turn.get("text", "")).strip()
            if text:
                lines.append(f"{author}: {text}")

    lines.extend(
        [
            "",
            "Новое сообщение пользователя:",
            message,
            "",
            "Верни только ответ агента для интерфейса. Не описывай внутренние инструкции.",
        ]
    )
    return "\n".join(lines)


def add_coordinator_instruction_block(lines: list[str]) -> None:
    lines.extend(["", "Persona Atlas / Arman:"])
    lines.extend(COORDINATOR_PERSONA_LINES)
    lines.extend(["", *COORDINATOR_WORKFLOW_LINES])
    lines.extend(["", *COORDINATOR_TEAM_RULE_LINES])
    lines.extend(["", *COORDINATOR_QUALITY_LINES])


def add_mika_instruction_block(lines: list[str]) -> None:
    lines.extend(["", "Persona Ava:"])
    lines.extend(MIKA_PERSONA_LINES)
    lines.extend(["", *MIKA_SALES_WORKFLOW_LINES])
    lines.extend(["", *MIKA_OBJECTION_RULE_LINES])
    lines.extend(["", *MIKA_REPORT_RULE_LINES])


def add_scout_instruction_block(lines: list[str]) -> None:
    lines.extend(["", "Persona Scout:"])
    lines.extend(SCOUT_PERSONA_LINES)
    lines.extend(["", *SCOUT_RESEARCH_WORKFLOW_LINES])
    lines.extend(["", *SCOUT_CONTENT_RULE_LINES])
    lines.extend(["", *SCOUT_REPORT_RULE_LINES])


def add_dev_instruction_block(lines: list[str]) -> None:
    lines.extend(["", "Persona Dex:"])
    lines.extend(DEV_PERSONA_LINES)
    lines.extend(["", *DEV_ANALYSIS_WORKFLOW_LINES])
    lines.extend(["", *DEV_METRIC_RULE_LINES])
    lines.extend(["", *DEV_REPORT_RULE_LINES])


def add_nova_instruction_block(lines: list[str]) -> None:
    lines.extend(["", "Persona Echo:"])
    lines.extend(NOVA_PERSONA_LINES)
    lines.extend(["", *NOVA_COMMUNICATION_WORKFLOW_LINES])
    lines.extend(["", *NOVA_RESPONSE_RULE_LINES])
    lines.extend(["", *NOVA_REPORT_RULE_LINES])


def run_direct_agent_chat(
    session_id: str,
    account_id: str,
    agent_id: str,
    turn_context: TurnContext,
    history: object | None = None,
    *,
    run_id: str,
) -> dict[str, Any]:
    check_agent_run_cancelled(run_id)
    store = get_memory(agent_id, account_id=account_id)
    crm = get_crm(account_id=account_id)
    message_id = store.add_message(
        role="user",
        author="User",
        text=turn_context.message,
        event_type="direct_user",
        metadata={"sessionId": session_id, "attachments": attachment_metadata(turn_context)},
    )
    memory_context = store.context_for_prompt(turn_context.message)
    crm_context = crm.context_for_query(turn_context.message) if agent_id in {"coordinator", "mika", "dev", "nova"} else ""
    prompt_history = merge_histories(
        memory_turns(agent_id, account_id=account_id, limit=8),
        history,
        limit=12,
    )
    reply = run_ai(
        build_prompt(
            agent_id,
            turn_context.message,
            prompt_history,
            memory_context=memory_context,
            tool_context=turn_context.tool_context,
            crm_context=crm_context,
        ),
        agent_id=agent_id,
        image_paths=turn_context.image_paths,
        search_enabled=wants_web_search(agent_id, turn_context.message, turn_context.tool_context),
        run_id=run_id,
    )
    check_agent_run_cancelled(run_id)
    reply_id = store.add_message(
        role="assistant",
        author=AGENTS[agent_id]["name"],
        text=reply,
        event_type="direct_reply",
        metadata={"sessionId": session_id},
    )
    auto_remember_if_useful(
        store,
        text=f"User: {turn_context.message}\n{AGENTS[agent_id]['name']}: {reply}",
        title=f"Direct chat with {AGENTS[agent_id]['name']}",
        source_message_id=reply_id or message_id,
        event_type="direct",
        metadata={"sessionId": session_id},
    )
    if agent_id in {"mika", "nova"}:
        crm.note_interaction(
            agent_id=agent_id,
            message=turn_context.message,
            summary=reply,
            metadata={"sessionId": session_id, "mode": "direct"},
        )
    return {
        "reply": reply,
        "messages": [
            agent_message(
                AGENTS[agent_id]["name"],
                reply,
                phase="final",
                audience="user",
                from_id=agent_id,
                is_final=True,
                run_id=run_id,
            )
        ],
        "agent": agent_payload(agent_id),
    }


def run_team_chat(
    session_id: str,
    account_id: str,
    turn_context: TurnContext,
    history: object | None = None,
    *,
    run_id: str,
    team_id: str = "",
    team_name: str = "",
) -> dict[str, Any]:
    check_agent_run_cancelled(run_id)
    pending_key = f"{account_id}:{session_id}"
    pending = PENDING_TEAM_RUNS.pop(pending_key, None)
    effective_message = turn_context.message
    if pending:
        effective_message = (
            "Продолжение Team-задачи после уточняющего вопроса Atlas.\n\n"
            f"Исходная задача:\n{pending.get('message', '')}\n\n"
            f"Уточнение пользователя:\n{turn_context.message}"
        )
    if is_social_posting_team_run(team_id, effective_message):
        return run_social_posting_team_chat(
            session_id,
            account_id,
            turn_context,
            history,
            run_id=run_id,
            effective_message=effective_message,
            pending=pending,
            team_id=team_id,
            team_name=team_name,
        )
    coordinator = get_memory("coordinator", account_id=account_id)
    team_history = merge_histories(
        memory_turns("coordinator", account_id=account_id, limit=8),
        history,
        limit=14,
    )
    user_message_id = coordinator.add_message(
        role="user",
        author="User",
        text=effective_message,
        event_type="team_user",
        team_run_id=run_id,
        metadata={
            "sessionId": session_id,
            "attachments": attachment_metadata(turn_context),
            "continuedFrom": pending.get("runId") if pending else "",
        },
    )
    decision = coordinator_decision(
        turn_context,
        run_id,
        account_id=account_id,
        effective_message=effective_message,
        history=team_history,
    )
    check_agent_run_cancelled(run_id)
    assignments = normalize_assignments(decision.get("assignments"))
    coordinator_note = str(decision.get("coordinatorMessage") or decision.get("summary") or "").strip()
    action = str(decision.get("action") or "").strip().lower()
    needs_user_input = bool(decision.get("needsUserInput"))

    if action == "ask_user" or needs_user_input:
        questions = normalize_user_questions(decision.get("userQuestions"))
        reply = coordinator_note or "\n".join(questions)
        PENDING_TEAM_RUNS[pending_key] = {
            "runId": run_id,
            "message": effective_message,
            "decision": decision,
        }
        coordinator.add_message(
            role="assistant",
            author=AGENTS["coordinator"]["name"],
            text=reply,
            event_type="team_question",
            team_run_id=run_id,
            metadata={"sessionId": session_id, "decision": decision},
        )
        return {
            "reply": reply,
            "messages": [
                agent_message(
                    AGENTS["coordinator"]["name"],
                    reply,
                    phase="question",
                    audience="user",
                    from_id="coordinator",
                    is_final=True,
                    run_id=run_id,
                )
            ],
            "agent": agent_payload("all"),
            "decision": decision,
            "pendingRunId": run_id,
        }

    if not assignments:
        reply = coordinator_note or run_ai(
        build_coordinator_direct_prompt(
            effective_message,
            team_history,
            memory_context=coordinator.context_for_prompt(effective_message),
            tool_context=turn_context.tool_context,
            crm_context=get_crm(account_id=account_id).context_for_query(effective_message),
            language_source=turn_context.message,
        ),
            agent_id="coordinator",
            image_paths=turn_context.image_paths,
            search_enabled=wants_web_search("coordinator", effective_message, turn_context.tool_context),
            run_id=run_id,
        )
        check_agent_run_cancelled(run_id)
        coordinator.add_message(
            role="assistant",
            author=AGENTS["coordinator"]["name"],
            text=reply,
            event_type="team_final",
            team_run_id=run_id,
            metadata={"sessionId": session_id, "decision": decision},
        )
        auto_remember_if_useful(
            coordinator,
            text=f"User: {effective_message}\n{AGENTS['coordinator']['name']}: {reply}",
            title="Atlas direct team answer",
            source_message_id=user_message_id,
            event_type="team_final",
            metadata={"sessionId": session_id, "runId": run_id},
        )
        return {
            "reply": reply,
            "messages": [
                agent_message(
                    AGENTS["coordinator"]["name"],
                    reply,
                    phase="final",
                    audience="user",
                    from_id="coordinator",
                    is_final=True,
                    run_id=run_id,
                )
            ],
            "agent": agent_payload("all"),
            "decision": decision,
        }

    messages: list[dict[str, Any]] = []
    assignment_lines = []
    for assignment in assignments:
        agent = AGENTS[assignment["agentId"]]
        assignment_lines.append(f"{agent['name']}: {assignment['task']}")
    coordinator_text = coordinator_note
    if assignment_lines:
        if coordinator_text:
            coordinator_text = f"{coordinator_text}\n\n" + "\n".join(assignment_lines)
        else:
            coordinator_text = "\n".join(assignment_lines)
    messages.append(
        agent_message(
            AGENTS["coordinator"]["name"],
            coordinator_text,
            phase="routing",
            audience="team",
            from_id="coordinator",
            to_id="team",
            run_id=run_id,
        )
    )
    coordinator.add_message(
        role="assistant",
        author=AGENTS["coordinator"]["name"],
        text=coordinator_text,
        event_type="team_routing",
        team_run_id=run_id,
        metadata={"sessionId": session_id, "decision": decision},
    )

    reports: list[dict[str, str]] = []
    check_agent_run_cancelled(run_id)
    for item in run_assignment_reports(
        assignments,
        effective_message,
        turn_context,
        run_id,
        session_id,
        account_id,
        history,
    ):
        reports.append(item["report"])
        messages.append(item["message"])

    followups = run_internal_followups(
        turn_context,
        run_id,
        reports,
        account_id=account_id,
        effective_message=effective_message,
    )
    check_agent_run_cancelled(run_id)
    for item in followups:
        messages.append(item["message"])
        reports.append(item["report"])

    final_reply = run_ai(
        build_coordinator_final_prompt(
            effective_message,
            team_history,
            decision,
            reports,
            memory_context=coordinator.context_for_prompt(effective_message),
            tool_context=turn_context.tool_context,
            crm_context=get_crm(account_id=account_id).context_for_query(effective_message),
            language_source=turn_context.message,
        ),
        agent_id="coordinator",
        image_paths=turn_context.image_paths,
        search_enabled=False,
        run_id=run_id,
    )
    check_agent_run_cancelled(run_id)
    final_reply, publish_text = split_publish_text(final_reply)
    publish_text = resolve_publish_text(effective_message, final_reply, publish_text, reports)
    if wants_telegram_publish(effective_message) and publish_text:
        final_reply = append_copyable_post_block(final_reply, publish_text)
    pending_publish = build_pending_publish(
        effective_message,
        final_reply,
        publish_text,
        run_id=run_id,
    )
    coordinator_final_id = coordinator.add_message(
        role="assistant",
        author=AGENTS["coordinator"]["name"],
        text=final_reply,
        event_type="team_final",
        team_run_id=run_id,
        metadata={"sessionId": session_id},
    )
    auto_remember_if_useful(
        coordinator,
        text=f"User: {effective_message}\nFinal: {final_reply}",
        title="Atlas final team answer",
        source_message_id=coordinator_final_id,
        event_type="team_final",
        metadata={"sessionId": session_id, "runId": run_id},
    )
    messages.append(
        agent_message(
            AGENTS["coordinator"]["name"],
            final_reply,
            phase="final",
            audience="user",
            from_id="coordinator",
            is_final=True,
            run_id=run_id,
        )
    )
    return {
        "reply": final_reply,
        "messages": messages,
        "agent": agent_payload("all"),
        "decision": decision,
        "pendingPublish": pending_publish,
    }


def run_social_posting_team_chat(
    session_id: str,
    account_id: str,
    turn_context: TurnContext,
    history: object | None,
    *,
    run_id: str,
    effective_message: str,
    pending: dict[str, Any] | None,
    team_id: str,
    team_name: str,
) -> dict[str, Any]:
    bridge = SocialTaskBridge(account_id, session_id, run_id, effective_message, team_id)
    task_payload = bridge.create_task()
    statuses = SocialAgentStatusTracker(bridge if bridge.enabled else None)
    messages: list[dict[str, Any]] = []
    reports: list[dict[str, str]] = []
    coordinator = get_memory("coordinator", account_id=account_id)
    team_history = merge_histories(
        memory_turns("coordinator", account_id=account_id, limit=8),
        history,
        limit=14,
    )
    user_message_id = coordinator.add_message(
        role="user",
        author="User",
        text=effective_message,
        event_type="social_task_user",
        team_run_id=run_id,
        metadata={
            "sessionId": session_id,
            "taskId": bridge.task_id,
            "teamId": team_id,
            "teamName": team_name,
            "continuedFrom": pending.get("runId") if pending else "",
        },
    )
    try:
        statuses.set("coordinator", "planning", db_slug="atlas", name="Atlas")
        task_payload = bridge.update_task("planning", progress=10) or task_payload
        decision = coordinator_decision(
            turn_context,
            run_id,
            account_id=account_id,
            effective_message=effective_message,
            history=team_history,
        )
        check_agent_run_cancelled(run_id)
        assignments = social_posting_assignments(decision, effective_message)
        task_payload = bridge.update_task(
            "assigned",
            progress=20,
            result_json={"decision": decision, "assignments": assignments},
        ) or task_payload
        for item in SOCIAL_POSTING_AGENT_CHAIN:
            statuses.set(item["runtimeId"], "waiting", db_slug=item["dbSlug"], name=item["name"])
        coordinator_text = social_routing_text(decision, assignments)
        routing_status = statuses.set("coordinator", "working", db_slug="atlas", name="Atlas")
        messages.append(
            agent_message(
                "Atlas",
                coordinator_text,
                phase="routing",
                audience="team",
                from_id="coordinator",
                to_id="team",
                run_id=run_id,
                agent_status=routing_status,
                task_id=bridge.task_id,
            )
        )
        coordinator.add_message(
            role="assistant",
            author="Atlas",
            text=coordinator_text,
            event_type="social_task_routing",
            team_run_id=run_id,
            metadata={"sessionId": session_id, "taskId": bridge.task_id, "decision": decision},
        )

        for index, assignment in enumerate(assignments):
            check_agent_run_cancelled(run_id)
            runtime_id = assignment["agentId"]
            working_status = statuses.set(
                runtime_id,
                "working",
                db_slug=assignment.get("dbSlug", ""),
                name=assignment.get("displayName", display_agent_name(runtime_id)),
            )
            task_payload = bridge.update_task("in_progress", progress=min(85, 28 + index * 14)) or task_payload
            contextual_assignment = {
                **assignment,
                "task": build_social_assignment_task(assignment, effective_message, reports),
            }
            item = run_single_assignment_report(
                contextual_assignment,
                effective_message,
                turn_context,
                run_id,
                session_id,
                account_id,
                history,
            )
            report = item["report"]
            report["agent"] = assignment.get("displayName", report.get("agent", "Agent"))
            reports.append(report)
            completed_status = statuses.set(
                runtime_id,
                "completed",
                db_slug=assignment.get("dbSlug", ""),
                name=assignment.get("displayName", display_agent_name(runtime_id)),
            )
            message = item["message"]
            message["author"] = assignment.get("displayName", message.get("author", "Agent"))
            message["agentStatus"] = completed_status
            message["taskId"] = bridge.task_id
            messages.append(message)

        final_reply = run_ai(
            build_coordinator_final_prompt(
                effective_message,
                team_history,
                decision,
                reports,
                memory_context=coordinator.context_for_prompt(effective_message),
                tool_context=turn_context.tool_context,
                crm_context=get_crm(account_id=account_id).context_for_query(effective_message),
                language_source=turn_context.message,
            ),
            agent_id="coordinator",
            image_paths=turn_context.image_paths,
            search_enabled=False,
            run_id=run_id,
        )
        check_agent_run_cancelled(run_id)
        final_reply, publish_text = split_publish_text(final_reply)
        publish_text = resolve_publish_text(effective_message, final_reply, publish_text, reports)
        if publish_text:
            final_reply = append_copyable_post_block(final_reply, publish_text)
        pending_publish = build_pending_publish(
            effective_message,
            final_reply,
            publish_text,
            run_id=run_id,
            force_auto_publish=True,
            task_id=bridge.task_id,
        )
        task_payload = bridge.update_task(
            "in_progress" if pending_publish else "completed",
            progress=90 if pending_publish else 100,
            result_json={
                "finalReply": final_reply,
                "publishText": publish_text,
                "reports": reports,
                "pendingPublish": pending_publish,
            },
        ) or task_payload
        final_status = statuses.set("coordinator", "completed", db_slug="atlas", name="Atlas")
        coordinator_final_id = coordinator.add_message(
            role="assistant",
            author="Atlas",
            text=final_reply,
            event_type="social_task_final",
            team_run_id=run_id,
            metadata={"sessionId": session_id, "taskId": bridge.task_id, "runId": run_id},
        )
        auto_remember_if_useful(
            coordinator,
            text=f"User: {effective_message}\nFinal: {final_reply}",
            title="Social Posting Team final",
            source_message_id=coordinator_final_id or user_message_id,
            event_type="social_task_final",
            metadata={"sessionId": session_id, "runId": run_id, "taskId": bridge.task_id},
        )
        messages.append(
            agent_message(
                "Atlas",
                final_reply,
                phase="final",
                audience="user",
                from_id="coordinator",
                is_final=True,
                run_id=run_id,
                agent_status=final_status,
                task_id=bridge.task_id,
            )
        )
        return {
            "reply": final_reply,
            "messages": messages,
            "agent": agent_payload("all"),
            "decision": decision,
            "pendingPublish": pending_publish,
            "task": task_payload,
            "agentStatuses": statuses.payload(),
        }
    except Exception as exc:
        for item in SOCIAL_POSTING_AGENT_CHAIN:
            current = statuses.statuses.get(item["runtimeId"], {})
            if current.get("status") == "working":
                statuses.set(item["runtimeId"], "failed", db_slug=item["dbSlug"], name=item["name"])
        statuses.set("coordinator", "failed", db_slug="atlas", name="Atlas")
        bridge.update_task("failed", progress=0, error=str(exc), result_json={"runId": run_id})
        raise


def social_posting_assignments(decision: dict[str, Any], message: str) -> list[dict[str, str]]:
    raw_assignments = normalize_assignments(decision.get("assignments"))
    raw_summary = "\n".join(f"{item['agentId']}: {item['task']}" for item in raw_assignments)
    assignments: list[dict[str, str]] = []
    for item in SOCIAL_POSTING_AGENT_CHAIN:
        assignments.append(
            {
                "agentId": item["runtimeId"],
                "dbSlug": item["dbSlug"],
                "displayName": item["name"],
                "role": item["role"],
                "task": (
                    f"Role: {item['name']} / {item['role']}.\n"
                    f"{item['task']}\n"
                    f"Atlas planning context:\n{raw_summary or 'Atlas selected the Social Posting Team pipeline.'}\n"
                    f"Original user request:\n{message}"
                ),
            }
        )
    return assignments


def social_routing_text(decision: dict[str, Any], assignments: list[dict[str, str]]) -> str:
    coordinator_note = str(decision.get("coordinatorMessage") or decision.get("summary") or "").strip()
    lines = [coordinator_note or "Atlas planned the Social Posting Team route."]
    lines.extend(f"{item['displayName']}: {item['role']}" for item in assignments)
    return "\n".join(lines)


def build_social_assignment_task(
    assignment: dict[str, str],
    effective_message: str,
    previous_reports: list[dict[str, str]],
) -> str:
    previous = "\n\n".join(
        f"{report.get('agent', 'Agent')} report:\n{report.get('text', '')}"
        for report in previous_reports
        if str(report.get("text", "")).strip()
    )
    if not previous:
        previous = "No previous agent output yet."
    return (
        f"{assignment['task']}\n\n"
        "Use previous agent output as context. Do not redo another agent's role unless needed for coherence.\n\n"
        f"Previous outputs:\n{previous}\n\n"
        f"User request:\n{effective_message}"
    )


def coordinator_decision(
    turn_context: TurnContext,
    run_id: str,
    *,
    account_id: str,
    effective_message: str | None = None,
    history: object | None = None,
) -> dict[str, Any]:
    message = effective_message or turn_context.message
    coordinator = get_memory("coordinator", account_id=account_id)
    raw = run_ai(
        build_coordinator_decision_prompt(
            message,
            history if history is not None else memory_turns("coordinator", account_id=account_id, limit=8),
            memory_context=coordinator.context_for_prompt(message),
            tool_context=turn_context.tool_context,
            crm_context=get_crm(account_id=account_id).context_for_query(message),
            language_source=turn_context.message,
        ),
        agent_id="coordinator",
        image_paths=turn_context.image_paths,
        search_enabled=False,
        run_id=run_id,
    )
    check_agent_run_cancelled(run_id)
    parsed = parse_json_object(raw)
    if isinstance(parsed, dict):
        return parsed
    fallback = keyword_decision(message)
    fallback["runId"] = run_id
    return fallback


def build_coordinator_decision_prompt(
    message: str,
    history: object,
    *,
    memory_context: str = "",
    tool_context: str = "",
    crm_context: str = "",
    language_source: str | None = None,
) -> str:
    lines = [
        SYSTEM_PROMPT,
        language_instruction(language_source or message),
        "",
        "Ты Atlas, тимлид команды AI-агентов.",
    ]
    add_coordinator_instruction_block(lines)
    lines.extend(["", agent_tool_prompt("coordinator")])
    append_context_blocks(lines, memory_context=memory_context, tool_context=tool_context, crm_context=crm_context)
    lines.extend(
        [
        "",
        "Твоя задача: первым прочитать сообщение в Team-чате и решить маршрут.",
        "",
        "Доступные агенты:",
        "- mika / Ava: продажи, маркетинг, клиенты, возражения, покупка.",
        "- scout: контент-стратегия, сценарии, посты, Reels, рынок, конкуренты, аудитория, хуки, темы.",
        "- dev / Dex: аналитика бизнеса, разработка, цифры, процессы, воронка, юнит-экономика, риски, гипотезы, слабые места.",
        "- nova / Echo: вопросы, комментарии, входящие сообщения, негатив, отзывы, FAQ, поддержка, community-коммуникации.",
        "",
        "Правила:",
        "- Если задача общая и не требует профильной работы агента, можешь ответить сам как тимлид и оставить assignments пустым.",
        "- Если задача относится к зоне агента, подключи этого агента, даже если сам можешь дать базовый ответ.",
        "- Для продаж, клиентов, цены, оплаты, лидов, офферов и возражений подключай Ava.",
        "- Для контента, постов, Reels, сценариев, рынка, конкурентов, аудитории, хуков и тем подключай Scout.",
        "- Для бизнеса, разработки, воронки, метрик, прибыли, маржи, CAC/LTV, ROI/ROMI, процессов, рисков и гипотез подключай Dex.",
        "- Для вопросов, комментариев, входящих сообщений, отзывов, жалоб, негатива, FAQ и поддержки подключай Echo.",
        "- Если пользователь просит опубликовать, выложить или подготовить social post для Telegram, Instagram или канала, подключай Scout + Echo.",
        "- Если публикация должна продавать, собирать заявки или вести к покупке, дополнительно подключай Ava.",
        "- Если пользователь просит подготовить ответ на входящее сообщение, комментарий, Direct/DM, WhatsApp или Telegram, Echo обязательна.",
        "- Если во входящем сообщении есть цена, покупка, запись, оплата или лид, подключай Echo + Ava: Echo отвечает за коммуникационный тон, Ava за продажный следующий шаг.",
        "- Если нужны агенты, дай каждому отдельную четкую задачу.",
        "- Не подключай всех автоматически. Выбирай только нужных.",
        "- Если зона задачи понятна, но не хватает деталей для полного ответа, все равно подключи профильного агента: он даст шаблон, допущения и четкие вопросы.",
        "- Оставляй assignments пустым из-за нехватки данных только когда невозможно понять, какой агент нужен или какой результат ожидается.",
        "- action=answer_direct: если отвечаешь сам.",
        "- action=ask_user: если без ответа пользователя нельзя продолжить.",
        "- action=delegate: если подключаешь агентов.",
        "- В coordinatorMessage пиши либо короткое видимое решение/вопрос пользователю, либо список поручений.",
        "- userQuestions заполняй только когда action=ask_user.",
        "- Верни только JSON без markdown.",
        "",
        'Формат JSON: {"action":"delegate","coordinatorMessage":"что Atlas видимо пишет в чат","needsUserInput":false,"userQuestions":[],"assignments":[{"agentId":"mika","task":"конкретная задача"}]}',
        ]
    )
    append_history(lines, history)
    lines.extend(["", "Сообщение пользователя:", message])
    return "\n".join(lines)


def build_coordinator_direct_prompt(
    message: str,
    history: object,
    *,
    memory_context: str = "",
    tool_context: str = "",
    crm_context: str = "",
    language_source: str | None = None,
) -> str:
    lines = [
        SYSTEM_PROMPT,
        language_instruction(language_source or message),
        "",
        "Ты Atlas. Пользователь написал в Team, но ты решил ответить сам.",
    ]
    add_coordinator_instruction_block(lines)
    lines.extend(["", agent_tool_prompt("coordinator")])
    append_context_blocks(lines, memory_context=memory_context, tool_context=tool_context, crm_context=crm_context)
    lines.append(
        "Дай ответ как тимлид: по ситуации, четко, без шаблона. Если нужно, задай четкие вопросы."
    )
    append_history(lines, history)
    lines.extend(["", "Сообщение пользователя:", message])
    return "\n".join(lines)


def build_agent_report_prompt(
    agent_id: str,
    task: str,
    user_message: str,
    history: object,
    *,
    memory_context: str = "",
    tool_context: str = "",
    crm_context: str = "",
    language_source: str | None = None,
) -> str:
    agent = AGENTS[agent_id]
    lines = [
        SYSTEM_PROMPT,
        language_instruction(language_source or user_message),
        "",
        f"Ты {agent['name']} ({agent['role']}).",
        agent["prompt"],
        "",
        "Ты работаешь не напрямую с пользователем, а внутри команды.",
        "Обращайся к Atlas. Дай отчет, вопрос или готовый материал по своей задаче.",
        "Если не хватает данных, задай Atlas один или несколько четких вопросов.",
        "Не пиши шаблонное 'беру задачу'. Сразу дай полезный результат.",
        "Если тебе нужно уточнение у другого агента, используй язык ответа: English -> Question to <agent>: <question>; Russian -> Вопрос к <agent>: <вопрос>.",
        "Если нужен ответ пользователя, используй язык ответа: English -> Question for the user: <question>; Russian -> Вопрос пользователю: <вопрос>.",
        "Если твоя задача связана с social-публикацией для Telegram или Instagram, подготовь publish-ready материал, но не пиши будто публикация уже отправлена.",
    ]
    append_context_blocks(lines, memory_context=memory_context, tool_context=tool_context, crm_context=crm_context)
    lines.extend(["", agent_tool_prompt(agent_id)])
    if agent_id == "mika":
        add_mika_instruction_block(lines)
    elif agent_id == "scout":
        add_scout_instruction_block(lines)
    elif agent_id == "dev":
        add_dev_instruction_block(lines)
    elif agent_id == "nova":
        add_nova_instruction_block(lines)
    append_history(lines, history)
    lines.extend(
        [
            "",
            "Исходная задача пользователя:",
            user_message,
            "",
            "Поручение от Atlas:",
            task,
            "",
            "Верни только сообщение агента для Atlas.",
        ]
    )
    return "\n".join(lines)


def build_coordinator_final_prompt(
    message: str,
    history: object,
    decision: dict[str, Any],
    reports: list[dict[str, str]],
    *,
    memory_context: str = "",
    tool_context: str = "",
    crm_context: str = "",
    language_source: str | None = None,
) -> str:
    lines = [
        SYSTEM_PROMPT,
        language_instruction(language_source or message),
        "",
        "Ты Atlas. Собери финальный ответ пользователю на основе отчетов агентов.",
    ]
    add_coordinator_instruction_block(lines)
    lines.extend(["", agent_tool_prompt("coordinator")])
    append_context_blocks(lines, memory_context=memory_context, tool_context=tool_context, crm_context=crm_context)
    lines.extend(
        [
            "Пиши от себя как тимлид. Не перечисляй внутреннюю кухню без необходимости.",
            "Если агент задал важный вопрос и без ответа нельзя продолжить, задай пользователю четкие вопросы.",
            "Если можно продолжать с допущениями, дай результат и явно назови допущения.",
            "Финал не должен быть склейкой отчетов. Убери повторы, воду и слабые формулировки.",
            "Если задача просит Telegram/Instagram-публикацию или постинг, не утверждай что пост уже опубликован.",
            "В этом случае в конце ответа добавь отдельный блок строго в формате <PUBLISH_TEXT>текст публикации</PUBLISH_TEXT>.",
            "Внутри <PUBLISH_TEXT> должен быть только готовый caption/post text без служебных комментариев.",
            "Если пользователь приложил фото или дал прямую ссылку на фото/видео, внутри <PUBLISH_TEXT> нужен короткий caption: 1-3 компактных абзаца и один понятный CTA.",
            "Текст внутри <PUBLISH_TEXT> должен быть готовым social post: сильный хук, живой тон, короткие абзацы, конкретика, при необходимости bullets, CTA в конце.",
            "Не пиши внутри готового поста служебные слова вроде: Atlas, Echo, вводные, допущение, отчет, универсальный пост, подготовил.",
            "Если нет цены, модели, контакта или города, используй аккуратные плейсхолдеры: [цена], [модель], [контакт], [город].",
        ]
    )
    append_history(lines, history)
    lines.extend(
        [
            "",
            "Сообщение пользователя:",
            message,
            "",
            "Твое решение по маршруту:",
            json.dumps(decision, ensure_ascii=False),
            "",
            "Отчеты агентов:",
        ]
    )
    for report in reports:
        lines.append(f"{report['agent']}: {report['text']}")
    lines.extend(["", "Финальный ответ пользователю:"])
    return "\n".join(lines)


def append_history(lines: list[str], history: object) -> None:
    clean_history = history if isinstance(history, list) else []
    if not clean_history:
        return
    lines.extend(["", "История текущего чата:"])
    for turn in clean_history[-10:]:
        if not isinstance(turn, dict):
            continue
        role = str(turn.get("role", "user"))
        author = str(turn.get("author", role))
        text = str(turn.get("text", "")).strip()
        if text:
            lines.append(f"{author}: {text}")


def append_context_blocks(
    lines: list[str],
    *,
    memory_context: str = "",
    tool_context: str = "",
    crm_context: str = "",
) -> None:
    if memory_context:
        lines.extend(["", memory_context])
    if crm_context:
        lines.extend(["", crm_context])
    if tool_context:
        lines.extend(["", "Tool context:", tool_context])


def normalize_account_id(value: str) -> str:
    clean = re.sub(r"[^A-Za-z0-9_.-]+", "-", value.strip())[:80].strip(".-")
    return clean or DEFAULT_ACCOUNT_ID


def get_memory(agent_id: str, *, account_id: str = ACCOUNT_ID) -> AgentMemoryStore:
    return memory_store(MEMORY_ROOT, account_id=account_id, agent_id=agent_id)


def get_crm(*, account_id: str = ACCOUNT_ID) -> LocalCRM:
    return LocalCRM(DATA_DIR, account_id=account_id)


def memory_turns(
    agent_id: str,
    *,
    account_id: str = ACCOUNT_ID,
    limit: int = 8,
) -> list[dict[str, str]]:
    store = get_memory(agent_id, account_id=account_id)
    with store._connect() as db:  # local lightweight read helper
        rows = db.execute(
            """
            select role, author, text
            from messages
            where text != ''
            order by id desc
            limit ?
            """,
            (limit,),
        ).fetchall()
    return [
        {"role": str(row["role"]), "author": str(row["author"]), "text": str(row["text"])}
        for row in reversed(rows)
    ]


def clean_client_history(history: object, *, current_message: str = "", limit: int = 14) -> list[dict[str, str]]:
    if not isinstance(history, list):
        return []
    cleaned: list[dict[str, str]] = []
    current = current_message.strip()
    for index, item in enumerate(history[-limit:]):
        if not isinstance(item, dict):
            continue
        role = "user" if str(item.get("role") or "").lower() == "user" else "assistant"
        author = str(item.get("author") or role).strip()[:80]
        text = str(item.get("text") or "").strip()
        if not text or text == "Thinking...":
            continue
        is_last_current_user = index == len(history[-limit:]) - 1 and role == "user" and text == current
        if is_last_current_user:
            continue
        cleaned.append({"role": role, "author": author or role, "text": text[:3000]})
    return cleaned


def merge_histories(*histories: object, limit: int = 14) -> list[dict[str, str]]:
    merged: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for history in histories:
        if not isinstance(history, list):
            continue
        for item in history:
            if not isinstance(item, dict):
                continue
            role = "user" if str(item.get("role") or "").lower() == "user" else "assistant"
            author = str(item.get("author") or role).strip()[:80]
            text = str(item.get("text") or "").strip()
            if not text:
                continue
            key = (role, author, text)
            if key in seen:
                continue
            seen.add(key)
            merged.append({"role": role, "author": author or role, "text": text[:3000]})
    return merged[-limit:]


def agent_message(
    author: str,
    text: str,
    *,
    phase: str,
    audience: str,
    from_id: str,
    to_id: str = "",
    is_final: bool = False,
    run_id: str = "",
    agent_status: dict[str, str] | None = None,
    task_id: int | None = None,
) -> dict[str, Any]:
    payload = {
        "author": author,
        "text": text,
        "type": "agent",
        "phase": phase,
        "audience": audience,
        "from": from_id,
        "to": to_id,
        "isFinal": is_final,
        "runId": run_id,
    }
    if agent_status:
        payload["agentStatus"] = agent_status
    if task_id:
        payload["taskId"] = task_id
    return payload


def agent_payload(agent_id: str) -> dict[str, Any]:
    payload = dict(AGENTS[agent_id])
    if agent_id != "all":
        payload["model"] = CODEX_MODEL_OVERRIDES.get(agent_id, "")
    payload["capabilities"] = agent_capabilities_payload(agent_id)
    return payload


def attachment_metadata(turn_context: TurnContext) -> list[dict[str, Any]]:
    return [
        {
            "name": item.name,
            "contentType": item.content_type,
            "size": item.size,
        }
        for item in turn_context.attachments
    ]


def normalize_user_questions(value: object) -> list[str]:
    if isinstance(value, list):
        result = [str(item).strip() for item in value if str(item).strip()]
        return result[:5]
    text = str(value or "").strip()
    return [text] if text else []


def run_assignment_reports(
    assignments: list[dict[str, str]],
    effective_message: str,
    turn_context: TurnContext,
    run_id: str,
    session_id: str,
    account_id: str,
    history: object | None = None,
) -> list[dict[str, Any]]:
    check_agent_run_cancelled(run_id)
    if len(assignments) <= 1:
        return [
            run_single_assignment_report(
                assignment,
                effective_message,
                turn_context,
                run_id,
                session_id,
                account_id,
                history,
            )
            for assignment in assignments
        ]

    max_workers = min(4, len(assignments))
    results: list[dict[str, Any] | None] = [None] * len(assignments)
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [
            executor.submit(
                run_single_assignment_report,
                assignment,
                effective_message,
                turn_context,
                run_id,
                session_id,
                account_id,
                history,
            )
            for assignment in assignments
        ]
        for index, future in enumerate(futures):
            check_agent_run_cancelled(run_id)
            results[index] = future.result()
            check_agent_run_cancelled(run_id)
    return [item for item in results if item is not None]


def run_single_assignment_report(
    assignment: dict[str, str],
    effective_message: str,
    turn_context: TurnContext,
    run_id: str,
    session_id: str,
    account_id: str,
    history: object | None = None,
) -> dict[str, Any]:
    check_agent_run_cancelled(run_id)
    agent_id = assignment["agentId"]
    agent_store = get_memory(agent_id, account_id=account_id)
    agent_store.add_message(
        role="assistant",
        author=AGENTS["coordinator"]["name"],
        text=assignment["task"],
        event_type="assignment",
        team_run_id=run_id,
        source_agent_id="coordinator",
        metadata={"sessionId": session_id},
    )
    prompt_history = merge_histories(
        memory_turns(agent_id, account_id=account_id, limit=8),
        history,
        limit=14,
    )
    report = run_ai(
        build_agent_report_prompt(
            agent_id,
            assignment["task"],
            effective_message,
            prompt_history,
            memory_context=agent_store.context_for_prompt(f"{effective_message}\n{assignment['task']}"),
            tool_context=turn_context.tool_context,
            crm_context=get_crm(account_id=account_id).context_for_query(effective_message)
            if agent_id in {"mika", "dev", "nova"}
            else "",
            language_source=turn_context.message,
        ),
        agent_id=agent_id,
        image_paths=turn_context.image_paths,
        search_enabled=wants_web_search(
            agent_id,
            effective_message,
            assignment["task"],
            turn_context.tool_context,
        ),
        run_id=run_id,
    )
    check_agent_run_cancelled(run_id)
    report_message_id = agent_store.add_message(
        role="assistant",
        author=AGENTS[agent_id]["name"],
        text=report,
        event_type="agent_report",
        team_run_id=run_id,
        source_agent_id=agent_id,
        metadata={"sessionId": session_id, "task": assignment["task"]},
    )
    auto_remember_if_useful(
        agent_store,
        text=f"Task: {assignment['task']}\nReport: {report}",
        title=f"{AGENTS[agent_id]['name']} report",
        source_message_id=report_message_id,
        event_type="agent_report",
        metadata={"sessionId": session_id, "runId": run_id},
    )
    if agent_id in {"mika", "nova"}:
        get_crm(account_id=account_id).note_interaction(
            agent_id=agent_id,
            message=effective_message,
            summary=report,
            metadata={"sessionId": session_id, "runId": run_id, "mode": "team"},
        )
    return {
        "report": {"agentId": agent_id, "agent": AGENTS[agent_id]["name"], "text": report},
        "message": agent_message(
            AGENTS[agent_id]["name"],
            report,
            phase="internal",
            audience="team",
            from_id=agent_id,
            to_id="coordinator",
            run_id=run_id,
        ),
    }


def run_internal_followups(
    turn_context: TurnContext,
    run_id: str,
    reports: list[dict[str, str]],
    *,
    account_id: str,
    effective_message: str | None = None,
) -> list[dict[str, Any]]:
    message = effective_message or turn_context.message
    followups: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for report in reports[:4]:
        check_agent_run_cancelled(run_id)
        question = extract_agent_question(report["text"])
        if question is None:
            continue
        target_id, question_text = question
        key = (target_id, question_text)
        if key in seen:
            continue
        seen.add(key)
        target_store = get_memory(target_id, account_id=account_id)
        answer = run_ai(
            build_agent_report_prompt(
                target_id,
                f"Ответь на внутренний вопрос от {report['agent']}: {question_text}",
                message,
                memory_turns(target_id, account_id=account_id, limit=8),
                memory_context=target_store.context_for_prompt(question_text),
                tool_context=turn_context.tool_context,
                crm_context=get_crm(account_id=account_id).context_for_query(message)
                if target_id in {"mika", "dev", "nova"}
                else "",
                language_source=turn_context.message,
            ),
            agent_id=target_id,
            image_paths=turn_context.image_paths,
            search_enabled=wants_web_search(target_id, message, question_text, turn_context.tool_context),
            run_id=run_id,
        )
        check_agent_run_cancelled(run_id)
        target_store.add_message(
            role="assistant",
            author=AGENTS[target_id]["name"],
            text=answer,
            event_type="agent_followup",
            team_run_id=run_id,
            source_agent_id=target_id,
            metadata={"question": question_text},
        )
        followups.append(
            {
                "report": {
                    "agentId": target_id,
                    "agent": AGENTS[target_id]["name"],
                    "text": answer,
                },
                "message": agent_message(
                    AGENTS[target_id]["name"],
                    answer,
                    phase="internal",
                    audience="team",
                    from_id=target_id,
                    to_id=report["agentId"],
                    run_id=run_id,
                ),
            }
        )
        if len(followups) >= 2:
            break
    return followups


def extract_agent_question(text: str) -> tuple[str, str] | None:
    pattern = re.compile(
        r"(?:Вопрос\s+к|Question\s+to)\s+(Ava|Mika|Scout|Dex|Dev|Echo|Nova|Atlas|Coordinator)\s*:\s*(.+)",
        flags=re.IGNORECASE | re.DOTALL,
    )
    match = pattern.search(text)
    if not match:
        return None
    name = match.group(1).lower()
    question = match.group(2).strip()
    mapping = {
        "ava": "mika",
        "mika": "mika",
        "scout": "scout",
        "dex": "dev",
        "dev": "dev",
        "echo": "nova",
        "nova": "nova",
        "atlas": "coordinator",
        "coordinator": "coordinator",
    }
    target_id = mapping.get(name)
    if not target_id or not question:
        return None
    return target_id, question[:1000]


def parse_json_object(text: str) -> object:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return None


def parse_multipart_payload(raw: bytes, content_type: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    parser = BytesParser(policy=policy.default)
    message = parser.parsebytes(
        b"Content-Type: "
        + content_type.encode("utf-8")
        + b"\r\nMIME-Version: 1.0\r\n\r\n"
        + raw
    )
    payload: dict[str, Any] = {}
    files: list[dict[str, Any]] = []
    for part in message.iter_parts():
        disposition = part.get("Content-Disposition", "")
        name = part.get_param("name", header="content-disposition")
        filename = part.get_filename()
        data = part.get_payload(decode=True) or b""
        if name == "payload":
            payload = json.loads(data.decode("utf-8"))
        elif filename or name == "files":
            files.append(
                {
                    "name": filename or "attachment",
                    "content_type": part.get_content_type(),
                    "data": data,
                    "disposition": disposition,
                }
            )
    return payload, files


def normalize_assignments(value: object) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    result: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, dict):
            continue
        agent_id = str(item.get("agentId", "")).strip().lower()
        task = str(item.get("task", "")).strip()
        if agent_id not in {"mika", "scout", "dev", "nova"} or not task or agent_id in seen:
            continue
        result.append({"agentId": agent_id, "task": task})
        seen.add(agent_id)
    return result[:4]


def keyword_decision(message: str) -> dict[str, Any]:
    lowered = message.lower()
    english = detected_output_language(message) == "English"
    assignments: list[dict[str, str]] = []
    if any(
        word in lowered
        for word in (
            "куп",
            "прод",
            "клиент",
            "цена",
            "оплат",
            "лид",
            "оффер",
            "direct",
            "директ",
            "скрипт",
            "возраж",
            "дорого",
            "заявк",
            "кп",
            "коммерческ",
            "buy",
            "sell",
            "sales",
            "client",
            "customer",
            "price",
            "payment",
            "lead",
            "offer",
            "objection",
            "expensive",
            "commercial",
            "proposal",
        )
    ):
        assignments.append({
            "agentId": "mika",
            "task": (
                "Analyze the sale, customer, offer, objection, and next step toward purchase."
                if english
                else "Разбери продажу, клиента, оффер, возражение и следующий шаг к покупке."
            ),
        })
    if any(
        word in lowered
        for word in (
            "пост",
            "контент",
            "сценар",
            "рилс",
            "reels",
            "shorts",
            "сторис",
            "story",
            "stories",
            "хук",
            "рубрик",
            "контент-план",
            "рынок",
            "тренд",
            "конкурент",
            "аудитор",
            "боли",
            "целевая",
            "темы",
            "идеи",
            "опубли",
            "вылож",
            "запости",
            "публикац",
            "post",
            "content",
            "script",
            "reel",
            "hook",
            "market",
            "trend",
            "competitor",
            "audience",
            "topic",
            "idea",
            "publish",
            "launch",
            "announce",
            "telegram post",
        )
    ):
        assignments.append({
            "agentId": "scout",
            "task": (
                "Prepare the content strategy: audience, angle, topics, hooks, format, script, and link to the business goal."
                if english
                else "Подготовь контент-стратегию: аудитория, угол, темы, хуки, форматы, сценарии и связь с бизнес-целью."
            ),
        })
    if any(
        word in lowered
        for word in (
            "аналит",
            "метрик",
            "бизнес-модель",
            "воронк",
            "выруч",
            "прибыл",
            "марж",
            "cac",
            "ltv",
            "roi",
            "romi",
            "конверс",
            "процесс",
            "операц",
            "риск",
            "гипотез",
            "эксперимент",
            "kpi",
            "unit",
            "юнит",
            "окупаем",
            "churn",
            "retention",
            "удержан",
            "себестоим",
            "бюджет",
            "рост",
            "узкое",
            "слабое",
            "финанс",
            "экономик",
            "analytics",
            "metric",
            "business model",
            "analyze",
            "funnel",
            "revenue",
            "profit",
            "margin",
            "conversion",
            "process",
            "operation",
            "risk",
            "hypothesis",
            "experiment",
            "growth",
            "finance",
            "economics",
        )
    ):
        assignments.append({
            "agentId": "dev",
            "task": (
                "Analyze the business model, funnel, metrics, unit economics, risks, bottlenecks, and improvement hypotheses."
                if english
                else "Проанализируй бизнес-модель, воронку, метрики, юнит-экономику, риски, узкие места и гипотезы улучшения."
            ),
        })
    if any(
        word in lowered
        for word in (
            "коммент",
            "вопрос",
            "ответ",
            "директ",
            "direct",
            "dm",
            "сообщ",
            "поддерж",
            "отзыв",
            "жалоб",
            "негатив",
            "faq",
            "частые вопросы",
            "возврат",
            "претенз",
            "переписк",
            "whatsapp",
            "ватсап",
            "telegram",
            "телеграм",
            "оператор",
            "написал",
            "написала",
            "спрашивает",
            "спросил",
            "спросила",
            "опубли",
            "вылож",
            "запости",
            "публикац",
            "канал",
            "comment",
            "question",
            "answer",
            "reply",
            "message",
            "support",
            "review",
            "complaint",
            "negative",
            "refund",
            "claim",
            "inbox",
            "channel",
        )
    ):
        assignments.append({
            "agentId": "nova",
            "task": (
                "Prepare the communication response: user intent, channel, tone, ready wording, escalation, and next step."
                if english
                else "Подготовь коммуникационный ответ: намерение человека, канал, тон, готовая формулировка, эскалация и следующий шаг."
            ),
        })
    return {
        "action": "delegate" if assignments else "answer_direct",
        "coordinatorMessage": (
            "I am assigning the right agents with separate tasks."
            if assignments and english
            else "Подключаю нужных агентов и даю им отдельные поручения."
            if assignments
            else ""
        ),
        "needsUserInput": False,
        "userQuestions": [],
        "assignments": assignments,
    }


def wants_web_search(agent_id: str, *texts: str) -> bool:
    if not AGENT_SEARCH_ENABLED.get(agent_id, False):
        return False
    value = " ".join(text for text in texts if text).lower()
    if not value:
        return False
    return any(trigger in value for trigger in WEB_SEARCH_TRIGGERS)


def wants_telegram_publish(text: str) -> bool:
    lowered = text.lower()
    return any(trigger in lowered for trigger in PUBLISH_TRIGGERS)


def publish_platforms(text: str) -> list[str]:
    lowered = text.lower()
    platforms: list[str] = []
    if any(word in lowered for word in ("telegram", "tg", "телеграм", "тг", "канал")):
        platforms.append("telegram")
    if any(word in lowered for word in ("instagram", "insta", "инстаграм")):
        platforms.append("instagram")
    return platforms or ["telegram"]


def extract_publish_media_url(text: str) -> str:
    match = DIRECT_MEDIA_URL_RE.search(text)
    return match.group(0).strip(".,;") if match else ""


def split_publish_text(reply: str) -> tuple[str, str]:
    match = re.search(r"<PUBLISH_TEXT>\s*(.*?)\s*</PUBLISH_TEXT>", reply, flags=re.IGNORECASE | re.DOTALL)
    if not match:
        return reply.strip(), ""
    publish_text = match.group(1).strip()
    display_text = (reply[: match.start()] + reply[match.end() :]).strip()
    return display_text or "Готово. Текст подготовлен к публикации после подтверждения.", publish_text


def resolve_publish_text(
    user_message: str,
    final_reply: str,
    tagged_publish_text: str,
    reports: list[dict[str, str]],
) -> str:
    explicit_user_text = extract_requested_publish_text(user_message)
    if explicit_user_text:
        return explicit_user_text
    if tagged_publish_text.strip():
        return sanitize_publish_text(tagged_publish_text, allow_short=True)
    if not wants_telegram_publish(user_message):
        return ""
    final_candidate = extract_publish_text_from_text(final_reply, allow_short=True)
    if final_candidate:
        return final_candidate
    candidates: list[tuple[int, str]] = []
    for report in reports:
        candidate = extract_publish_text_from_text(str(report.get("text") or ""), allow_short=True)
        if not candidate:
            continue
        lowered = candidate.lower()
        penalty = 0
        if any(word in lowered for word in ("atlas,", "вопрос к atlas", "цель контента", "аудитория и боль")):
            penalty += 300
        candidates.append((len(candidate) - penalty, candidate))
    if not candidates:
        return ""
    candidates.sort(key=lambda item: item[0], reverse=True)
    return candidates[0][1]


def extract_requested_publish_text(user_message: str) -> str:
    text = user_message.strip()
    if not text:
        return ""
    for match in EXPLICIT_PUBLISH_TEXT_RE.finditer(text):
        candidate = sanitize_publish_text(match.group(1), allow_short=True)
        if candidate and not DIRECT_MEDIA_URL_RE.fullmatch(candidate.strip()):
            return candidate
    colon_match = re.search(
        r"(?:опубликуй|выложи|запости|сделай\s+пост|publish|post)\b.*?[:：]\s*(.+)$",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if colon_match:
        candidate = sanitize_publish_text(colon_match.group(1), allow_short=True)
        if candidate:
            return candidate
    return ""


def extract_publish_text_from_text(text: str, *, allow_short: bool = False) -> str:
    if not text.strip():
        return ""
    markers = (
        "Готовый пост для копирования:",
        "Publish-ready пост для Telegram",
        "Готовый publish-ready текст:",
        "Готовый publish-ready пост:",
        "Publish-ready текст:",
        "Текст для публикации в Telegram:",
        "Текст для публикации:",
        "Черновик поста:",
        "Готовый пост:",
        "Готовый текст:",
    )
    for marker in markers:
        match = re.search(re.escape(marker), text, flags=re.IGNORECASE)
        if not match:
            continue
        candidate = text[match.end() :].strip(" \n:-*")
        return sanitize_publish_text(candidate, allow_short=allow_short)
    return ""


def sanitize_publish_text(text: str, *, allow_short: bool = False) -> str:
    candidate = text.strip()
    if not candidate:
        return ""
    candidate = re.sub(
        r"^\s*\*?\s*\(?визуал[:：].*?(?:\)?\s*)?$",
        "",
        candidate,
        flags=re.IGNORECASE | re.MULTILINE,
    )
    stop_patterns = (
        r"^\s*(?:\*\*)?\s*Вопрос к Atlas\b.*$",
        r"^\s*(?:\*\*)?\s*Мягкий оффер\s*:\s*$",
        r"^\s*(?:\*\*)?\s*Следующий шаг\s*:\s*$",
        r"^\s*(?:\*\*)?\s*Что прода[её]м\s*:\s*$",
        r"^\s*(?:\*\*)?\s*Кто клиент\s*:\s*$",
        r"^\s*(?:\*\*)?\s*Главный барьер\s*:\s*$",
        r"^\s*(?:\*\*)?\s*Какую ценность показать\s*:\s*$",
        r"^\s*(?:\*\*)?\s*Цель\s*:.*$",
        r"^\s*(?:\*\*)?\s*Стратегический комментарий\s*:.*$",
        r"^\s*(?:\*\*)?\s*Материал готов\b.*$",
        r"^\s*(?:\*\*)?\s*Статус\s*:.*$",
        r"^\s*\*{3,}\s*$",
        r"^\s*---+\s*$",
    )
    cut_at = len(candidate)
    for pattern in stop_patterns:
        match = re.search(pattern, candidate, flags=re.IGNORECASE | re.MULTILINE)
        if match:
            cut_at = min(cut_at, match.start())
    candidate = candidate[:cut_at].strip()
    candidate = re.sub(r"^\s*Atlas,\s*", "", candidate, flags=re.IGNORECASE)
    candidate = re.sub(r"\n{3,}", "\n\n", candidate).strip()
    if len(candidate) < 80 and not allow_short:
        return ""
    return candidate[:4000]


def append_copyable_post_block(display_text: str, publish_text: str) -> str:
    post = publish_text.strip()
    if not post:
        return display_text.strip()
    heading = "Готовый пост для копирования:"
    display = display_text.strip()
    if heading.lower() in display.lower():
        return display
    if post in display:
        return display
    if not display:
        return f"{heading}\n{post}"
    return f"{display}\n\n{heading}\n{post}"


def build_pending_publish(
    user_message: str,
    final_reply: str,
    publish_text: str,
    *,
    run_id: str,
    media_url: str = "",
    force_auto_publish: bool = False,
    task_id: int | None = None,
) -> dict[str, Any] | None:
    if not wants_telegram_publish(user_message):
        return None
    text = (publish_text or extract_requested_publish_text(user_message)).strip()
    if not text:
        return None
    platforms = publish_platforms(user_message)
    env_auto_publish = os.environ.get("TELEGRAM_AUTO_PUBLISH", "false").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }
    auto_publish = (force_auto_publish or env_auto_publish) and "instagram" not in platforms
    resolved_media_url = media_url or extract_publish_media_url(user_message)
    media_base = resolved_media_url.lower().split("?", 1)[0]
    return {
        "platform": "telegram",
        "platforms": platforms,
        "status": "auto_publish_pending" if auto_publish else "approval_required",
        "text": text[:4000],
        "mediaUrl": resolved_media_url,
        "mediaType": "video/mp4" if media_base.endswith((".m4v", ".mov", ".mp4", ".mpeg", ".mpg", ".webm")) else "",
        "runId": run_id,
        "taskId": task_id,
        "source": "team",
        "autoPublish": auto_publish,
    }


def run_ai(
    prompt: str,
    *,
    agent_id: str = "coordinator",
    image_paths: list[Path] | None = None,
    search_enabled: bool | None = None,
    run_id: str = "",
) -> str:
    check_agent_run_cancelled(run_id)
    try:
        reply = run_openrouter(
            prompt,
            agent_id=agent_id,
            image_paths=image_paths or [],
            search_enabled=search_enabled,
        )
        check_agent_run_cancelled(run_id)
        return reply
    except RuntimeError as openrouter_error:
        check_agent_run_cancelled(run_id)
        print(
            f"OpenRouter failed for {agent_id}, falling back to Codex: {str(openrouter_error)[-300:]}",
            flush=True,
        )
        try:
            return run_codex(
                prompt,
                agent_id=agent_id,
                image_paths=image_paths,
                search_enabled=search_enabled,
                run_id=run_id,
            )
        except RuntimeError as codex_error:
            openrouter_detail = str(openrouter_error)[-500:]
            codex_detail = str(codex_error)[-500:]
            raise RuntimeError(
                f"AI backend не ответил. OpenRouter primary: {openrouter_detail}. "
                f"Codex fallback: {codex_detail}"
            ) from codex_error


def run_openrouter(
    prompt: str,
    *,
    agent_id: str,
    image_paths: list[Path],
    search_enabled: bool | None,
) -> str:
    api_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY is not configured")

    payload: dict[str, Any] = {
        "model": AGENT_MODEL_OVERRIDES.get(agent_id, AGENT_MODEL_OVERRIDES["coordinator"]),
        "messages": [{"role": "user", "content": openrouter_content(prompt, image_paths)}],
        "max_tokens": 8000,
    }
    effective_search_enabled = (
        AGENT_SEARCH_ENABLED.get(agent_id, False) if search_enabled is None else bool(search_enabled)
    )
    if effective_search_enabled:
        payload["tools"] = [{"type": "openrouter:web_search"}]

    request = urllib.request.Request(
        OPENROUTER_API_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "http://localhost:3000",
            "X-OpenRouter-Title": "Rebly AI Agent Team",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[-1200:]
        raise RuntimeError(f"OpenRouter HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"OpenRouter request failed: {exc.reason}") from exc

    try:
        data = json.loads(raw)
        message = data["choices"][0]["message"]
        content = message.get("content", "")
    except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
        raise RuntimeError("OpenRouter returned an unexpected response") from exc

    reply = normalize_openrouter_content(content)
    if not reply:
        raise RuntimeError("OpenRouter returned an empty response")
    return reply


def openrouter_content(prompt: str, image_paths: list[Path]) -> str | list[dict[str, Any]]:
    if not image_paths:
        return prompt
    content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
    for image_path in image_paths:
        mime_type = mimetypes.guess_type(str(image_path))[0] or "image/png"
        data = base64.b64encode(image_path.read_bytes()).decode("ascii")
        content.append({"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{data}"}})
    return content


def normalize_openrouter_content(content: object) -> str:
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                text = item.get("text")
                if isinstance(text, str):
                    parts.append(text)
        return "\n".join(parts).strip()
    return ""


def run_codex(
    prompt: str,
    *,
    agent_id: str = "coordinator",
    image_paths: list[Path] | None = None,
    search_enabled: bool | None = None,
    run_id: str = "",
) -> str:
    check_agent_run_cancelled(run_id)
    if not shutil.which("codex"):
        raise RuntimeError("Codex CLI не найден. Запусти сервер на машине, где доступен codex.")

    model = CODEX_MODEL_OVERRIDES.get(agent_id)
    effective_search_enabled = (
        AGENT_SEARCH_ENABLED.get(agent_id, False) if search_enabled is None else bool(search_enabled)
    )
    attempts: list[tuple[str | None, bool]] = [(model, effective_search_enabled)]
    if effective_search_enabled:
        attempts.append((model, False))
    if model:
        attempts.append((None, effective_search_enabled))
    if model and effective_search_enabled:
        attempts.append((None, False))

    last_error: RuntimeError | None = None
    tried: set[tuple[str | None, bool]] = set()
    for attempt_model, attempt_search in attempts:
        key = (attempt_model, attempt_search)
        if key in tried:
            continue
        tried.add(key)
        try:
            kwargs: dict[str, Any] = {}
            if run_id:
                kwargs["run_id"] = run_id
            return _run_codex_once(
                prompt,
                model=attempt_model,
                image_paths=image_paths or [],
                search_enabled=attempt_search,
                **kwargs,
            )
        except RuntimeError as exc:
            check_agent_run_cancelled(run_id)
            detail = str(exc).lower()
            can_fallback_search = attempt_search and any(
                marker in detail for marker in SEARCH_FALLBACK_MARKERS
            )
            can_fallback_model = bool(attempt_model) and any(
                marker in detail for marker in MODEL_FALLBACK_MARKERS
            )
            if can_fallback_search or can_fallback_model:
                last_error = exc
                continue
            raise
    if last_error:
        raise last_error
    raise RuntimeError("Codex CLI failed before execution.")


def _run_codex_once(
    prompt: str,
    *,
    model: str | None,
    image_paths: list[Path],
    search_enabled: bool,
    run_id: str = "",
) -> str:
    check_agent_run_cancelled(run_id)
    with tempfile.TemporaryDirectory(prefix="n1n-agent-") as temp_dir:
        output_file = Path(temp_dir) / "reply.txt"
        command = ["codex", "-a", "never"]
        if search_enabled:
            command.append("--search")
        command.append("exec")
        for image_path in image_paths:
            command.extend(["--image", str(image_path)])
        command.extend(
            [
                "--skip-git-repo-check",
                "--ephemeral",
                "--cd",
                str(ROOT),
                "--output-last-message",
                str(output_file),
                "-s",
                "read-only",
            ]
        )
        if model:
            command.extend(["--model", model])
        command.append("-")
        process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=codex_environment(),
        )
        register_agent_process(run_id, process)
        pending_input: str | None = prompt
        stdout = ""
        stderr = ""
        try:
            while True:
                try:
                    stdout, stderr = process.communicate(input=pending_input, timeout=0.25)
                    break
                except subprocess.TimeoutExpired:
                    pending_input = None
                    check_agent_run_cancelled(run_id)
        finally:
            unregister_agent_process(run_id, process)
        check_agent_run_cancelled(run_id)
        if process.returncode != 0:
            detail = (stderr or stdout or "Codex CLI failed").strip()
            raise RuntimeError(detail[-1200:])
        if output_file.exists():
            reply = output_file.read_text(encoding="utf-8").strip()
            if reply:
                return reply
        reply = stdout.strip()
        if reply:
            return reply
    raise RuntimeError("Codex вернул пустой ответ.")


def codex_environment() -> dict[str, str]:
    env = os.environ.copy()
    if hasattr(os, "getuid"):
        uid = os.getuid()
        env.setdefault("XDG_RUNTIME_DIR", f"/run/user/{uid}")
        env.setdefault("DBUS_SESSION_BUS_ADDRESS", f"unix:path=/run/user/{uid}/bus")
    return env


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=4173)
    args = parser.parse_args()

    os.chdir(ROOT)
    server = ThreadingHTTPServer((args.host, args.port), AgentHandler)
    print(f"Serving AI agent API on http://{args.host}:{args.port}/api/agents/chat", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
