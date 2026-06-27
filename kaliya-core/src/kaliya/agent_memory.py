from __future__ import annotations

import json
import re
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterator

from kaliya.text_safety import contains_secret_like_text, redact_sensitive_text

AGENT_IDS = {"coordinator", "mika", "scout", "dev", "nova"}
DEFAULT_ACCOUNT_ID = "local"


@dataclass(frozen=True)
class RetrievedMemory:
    title: str
    text: str
    kind: str
    score: float


class AgentMemoryStore:
    def __init__(self, root: Path, *, account_id: str, agent_id: str) -> None:
        if agent_id not in AGENT_IDS:
            raise ValueError(f"Unknown agent id: {agent_id}")
        self.root = root.resolve()
        self.account_id = safe_path_part(account_id)
        self.agent_id = agent_id
        self.database_path = (
            self.root / self.account_id / self.agent_id / "memory.sqlite3"
        ).resolve()
        ensure_inside(self.root, self.database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def add_message(
        self,
        *,
        role: str,
        author: str,
        text: str,
        event_type: str,
        team_run_id: str = "",
        source_agent_id: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> int:
        clean_text = redact_sensitive_text(text.strip())
        with self._connect() as db:
            cursor = db.execute(
                """
                insert into messages (
                    role, author, text, event_type, team_run_id, source_agent_id,
                    created_at, metadata_json
                )
                values (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    role,
                    author[:120],
                    clean_text,
                    event_type[:80],
                    team_run_id[:80],
                    source_agent_id[:80],
                    now_iso(),
                    json_dumps(metadata or {}),
                ),
            )
            return int(cursor.lastrowid)

    def remember(
        self,
        *,
        kind: str,
        title: str,
        body: str,
        source_message_id: int | None = None,
        confidence: float = 0.7,
        importance: float = 0.5,
        metadata: dict[str, Any] | None = None,
    ) -> int | None:
        clean_title = redact_sensitive_text(one_line(title, limit=180))
        clean_body = redact_sensitive_text(body.strip())
        if not clean_body:
            return None
        if contains_secret_like_text(body, title):
            clean_body = redact_sensitive_text(clean_body)
        fingerprint = memory_fingerprint(clean_title, clean_body)
        with self._connect() as db:
            existing = db.execute(
                "select id from memory_chunks where fingerprint = ? limit 1",
                (fingerprint,),
            ).fetchone()
            if existing:
                return int(existing["id"])
            cursor = db.execute(
                """
                insert into memories (
                    kind, status, title, body, source_message_id, confidence,
                    importance, created_at, updated_at, metadata_json
                )
                values (?, 'active', ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    kind[:40],
                    clean_title,
                    clean_body,
                    source_message_id,
                    float(confidence),
                    float(importance),
                    now_iso(),
                    now_iso(),
                    json_dumps(metadata or {}),
                ),
            )
            memory_id = int(cursor.lastrowid)
            chunk_text = one_line(clean_body, limit=2400)
            db.execute(
                """
                insert into memory_chunks (
                    memory_id, message_id, chunk_type, title, text, fingerprint,
                    token_estimate, created_at, updated_at, metadata_json
                )
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    memory_id,
                    source_message_id,
                    kind[:40],
                    clean_title,
                    chunk_text,
                    fingerprint,
                    max(1, len(chunk_text) // 4),
                    now_iso(),
                    now_iso(),
                    json_dumps(metadata or {}),
                ),
            )
            chunk_id = int(db.execute("select last_insert_rowid()").fetchone()[0])
            db.execute(
                """
                insert into memory_chunks_fts(rowid, title, text, chunk_type)
                values (?, ?, ?, ?)
                """,
                (chunk_id, clean_title, chunk_text, kind[:40]),
            )
            return memory_id

    def retrieve(self, query: str, *, limit: int = 5, max_chars: int = 3000) -> list[RetrievedMemory]:
        clean_query = fts_query(query)
        rows: list[sqlite3.Row] = []
        with self._connect() as db:
            if clean_query:
                try:
                    rows = db.execute(
                        """
                        select c.title, c.text, c.chunk_type,
                               bm25(memory_chunks_fts) as score
                        from memory_chunks_fts
                        join memory_chunks c on c.id = memory_chunks_fts.rowid
                        join memories m on m.id = c.memory_id
                        where memory_chunks_fts match ? and m.status = 'active'
                        order by score
                        limit ?
                        """,
                        (clean_query, limit),
                    ).fetchall()
                except sqlite3.OperationalError:
                    rows = []
            if not rows:
                rows = db.execute(
                    """
                    select c.title, c.text, c.chunk_type, 0.0 as score
                    from memory_chunks c
                    join memories m on m.id = c.memory_id
                    where m.status = 'active'
                    order by c.id desc
                    limit ?
                    """,
                    (limit,),
                ).fetchall()
        result: list[RetrievedMemory] = []
        remaining = max_chars
        for row in rows:
            text = str(row["text"])
            if remaining <= 0:
                break
            clipped = text[:remaining].rstrip()
            remaining -= len(clipped)
            result.append(
                RetrievedMemory(
                    title=str(row["title"]),
                    text=clipped,
                    kind=str(row["chunk_type"]),
                    score=float(row["score"]),
                )
            )
        return result

    def context_for_prompt(self, query: str, *, max_chars: int = 3000) -> str:
        memories = self.retrieve(query, max_chars=max_chars)
        if not memories:
            return ""
        lines = [f"Persistent memory for {self.agent_id}:"]
        for item in memories:
            lines.append(f"- [{item.kind}] {item.title}: {one_line(item.text, limit=700)}")
        return "\n".join(lines)

    def _init_schema(self) -> None:
        with self._connect() as db:
            db.executescript(
                """
                create table if not exists messages (
                    id integer primary key autoincrement,
                    role text not null,
                    author text not null,
                    text text not null default '',
                    event_type text not null default '',
                    team_run_id text not null default '',
                    source_agent_id text not null default '',
                    created_at text not null,
                    metadata_json text not null default '{}'
                );

                create index if not exists ix_messages_run
                    on messages(team_run_id, id);

                create table if not exists memories (
                    id integer primary key autoincrement,
                    kind text not null,
                    status text not null default 'active',
                    title text not null,
                    body text not null,
                    source_message_id integer,
                    confidence real not null default 0.7,
                    importance real not null default 0.5,
                    created_at text not null,
                    updated_at text not null,
                    metadata_json text not null default '{}',
                    foreign key(source_message_id) references messages(id) on delete set null
                );

                create index if not exists ix_memories_kind_status
                    on memories(kind, status, id);

                create table if not exists memory_chunks (
                    id integer primary key autoincrement,
                    memory_id integer,
                    message_id integer,
                    chunk_type text not null,
                    title text not null,
                    text text not null,
                    fingerprint text not null unique,
                    token_estimate integer not null default 0,
                    created_at text not null,
                    updated_at text not null,
                    metadata_json text not null default '{}',
                    foreign key(memory_id) references memories(id) on delete cascade,
                    foreign key(message_id) references messages(id) on delete set null
                );

                create virtual table if not exists memory_chunks_fts
                    using fts5(title, text, chunk_type);

                create table if not exists retrieval_log (
                    id integer primary key autoincrement,
                    query text not null,
                    selected_context_json text not null default '[]',
                    created_at text not null
                );
                """
            )

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.database_path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("pragma foreign_keys = on")
        connection.execute("pragma journal_mode = wal")
        connection.execute("pragma busy_timeout = 5000")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()


def auto_remember_if_useful(
    store: AgentMemoryStore,
    *,
    text: str,
    title: str,
    source_message_id: int | None,
    event_type: str,
    metadata: dict[str, Any] | None = None,
) -> int | None:
    value = text.strip()
    if len(value) < 80 and not is_explicit_memory(value):
        return None
    if contains_secret_like_text(value):
        value = redact_sensitive_text(value)
    kind = "explicit" if is_explicit_memory(value) else event_type or "auto"
    return store.remember(
        kind=kind[:40],
        title=title,
        body=value,
        source_message_id=source_message_id,
        confidence=0.85 if kind == "explicit" else 0.62,
        importance=0.8 if kind == "explicit" else 0.5,
        metadata=metadata,
    )


def memory_store(root: Path, *, account_id: str, agent_id: str) -> AgentMemoryStore:
    return AgentMemoryStore(root, account_id=account_id, agent_id=agent_id)


def is_explicit_memory(text: str) -> bool:
    return text.strip().lower().startswith((
        "запомни",
        "важно",
        "идея",
        "/important",
        "/idea",
        "remember:",
        "important:",
        "idea:",
    ))


def safe_path_part(value: str) -> str:
    clean = re.sub(r"[^A-Za-z0-9_.-]+", "-", value.strip())[:80].strip(".-")
    return clean or DEFAULT_ACCOUNT_ID


def ensure_inside(root: Path, path: Path) -> None:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError(f"Path must stay inside {root}") from exc


def fts_query(text: str) -> str:
    words = re.findall(r"[\wА-Яа-яЁё]{3,}", text.lower())
    return " OR ".join(dict.fromkeys(words[:12]))


def one_line(text: str, *, limit: int = 360) -> str:
    clean = " ".join(text.strip().split())
    if len(clean) <= limit:
        return clean
    return clean[: limit - 1].rstrip() + "..."


def memory_fingerprint(title: str, body: str) -> str:
    import hashlib

    payload = f"{title}\n{body}".encode("utf-8")
    return hashlib.blake2b(payload, digest_size=16).hexdigest()


def json_dumps(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")
