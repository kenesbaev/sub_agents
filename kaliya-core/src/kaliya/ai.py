from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass

from kaliya.config import Settings


@dataclass(frozen=True)
class ChatTurn:
    role: str
    text: str


class ChatMemory:
    """Short session history only. No SQLite, Markdown, KG, or vector memory."""

    def __init__(self, max_messages: int) -> None:
        self._max_messages = max_messages
        self._history: defaultdict[str, deque[ChatTurn]] = defaultdict(
            lambda: deque(maxlen=max_messages)
        )

    def get(self, session_id: str) -> list[ChatTurn]:
        if self._max_messages == 0:
            return []
        return list(self._history[session_id])

    def append(self, session_id: str, role: str, text: str) -> None:
        if self._max_messages == 0:
            return
        self._history[session_id].append(ChatTurn(role=role, text=text))

    def reset(self, session_id: str) -> None:
        self._history.pop(session_id, None)


class KaliyaCoreAI:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.memory = ChatMemory(settings.max_history_messages)

    def build_prompt(self, session_id: str, user_text: str, *, agent_prompt: str = "") -> str:
        turns = self.memory.get(session_id)
        lines = [
            self.settings.system_prompt,
            "",
            "You are working inside a five-agent business team.",
            "Use only current session history. Persistent memory is disabled.",
        ]
        if agent_prompt:
            lines.extend(["", "Current agent role:", agent_prompt])
        if turns:
            lines.extend(["", "Earlier messages:"])
            for turn in turns:
                label = "User" if turn.role == "user" else "Assistant"
                lines.append(f"{label}: {turn.text}")
        lines.extend(["", f"Current user message: {user_text}"])
        return "\n".join(lines)

    def record(self, session_id: str, user_text: str, assistant_text: str) -> None:
        self.memory.append(session_id, "user", user_text)
        self.memory.append(session_id, "assistant", assistant_text)
