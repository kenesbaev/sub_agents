from __future__ import annotations

from dataclasses import dataclass
from os import environ
from pathlib import Path

AI_PROVIDER_CODEX_CLI = "codex-cli"
AI_PROVIDER_OPENAI_API = "openai-api"
AI_PROVIDERS = {AI_PROVIDER_CODEX_CLI, AI_PROVIDER_OPENAI_API}

DEFAULT_SYSTEM_PROMPT = (
    "You are Kaliya, a concise AI assistant. "
    "Reply in Russian by default unless the user asks for another language. "
    "Help with business, content, sales, analytics, support, programming, Linux commands, "
    "debugging, and project planning. Be clear and practical. "
    "Do not print full secrets, tokens, passwords, private keys, or cookies."
)


@dataclass(frozen=True)
class Settings:
    ai_provider: str = AI_PROVIDER_CODEX_CLI
    openai_api_key: str | None = None
    openai_model: str = "gpt-5.4-mini"
    codex_model: str | None = "gpt-5.5"
    codex_timeout_seconds: int = 0
    codex_search_enabled: bool = False
    max_history_messages: int = 12
    workspace_root: Path = Path.cwd()
    system_prompt: str = DEFAULT_SYSTEM_PROMPT


def load_settings() -> Settings:
    ai_provider = environ.get("KALIYA_AI_PROVIDER", AI_PROVIDER_CODEX_CLI).strip().lower()
    if ai_provider not in AI_PROVIDERS:
        joined = ", ".join(sorted(AI_PROVIDERS))
        raise RuntimeError(f"KALIYA_AI_PROVIDER must be one of: {joined}")

    return Settings(
        ai_provider=ai_provider,
        openai_api_key=environ.get("OPENAI_API_KEY", "").strip() or None,
        openai_model=environ.get("OPENAI_MODEL", "gpt-5.4-mini").strip() or "gpt-5.4-mini",
        codex_model=environ.get("KALIYA_CODEX_MODEL", "gpt-5.5").strip() or None,
        codex_timeout_seconds=_int_env("KALIYA_CODEX_TIMEOUT_SECONDS", 0, minimum=0),
        codex_search_enabled=_bool_env("KALIYA_CODEX_SEARCH_ENABLED", False),
        max_history_messages=_int_env("KALIYA_MAX_HISTORY_MESSAGES", 12, minimum=0),
        workspace_root=Path(environ.get("KALIYA_WORKSPACE_ROOT", str(Path.cwd())).strip()),
        system_prompt=environ.get("KALIYA_SYSTEM_PROMPT", DEFAULT_SYSTEM_PROMPT).strip()
        or DEFAULT_SYSTEM_PROMPT,
    )


def _bool_env(name: str, default: bool) -> bool:
    value = environ.get(name)
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "y", "on"}:
        return True
    if normalized in {"0", "false", "no", "n", "off"}:
        return False
    raise RuntimeError(f"{name} must be true or false")


def _int_env(name: str, default: int, *, minimum: int) -> int:
    value = environ.get(name)
    if value is None or not value.strip():
        return default
    try:
        parsed = int(value)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer") from exc
    if parsed < minimum:
        raise RuntimeError(f"{name} must be >= {minimum}")
    return parsed
