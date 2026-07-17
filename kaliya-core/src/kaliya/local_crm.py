from __future__ import annotations

import json
import os
import re
import sqlite3
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterator

from kaliya.text_safety import redact_sensitive_text


try:
    CRM_MAX_INTERACTIONS = max(100, min(20_000, int(os.environ.get("AGENT_CRM_MAX_INTERACTIONS", "5000"))))
except ValueError:
    CRM_MAX_INTERACTIONS = 5000

_SCHEMA_INITIALIZATION_LOCK = threading.Lock()
_INITIALIZED_DATABASES: set[Path] = set()


@dataclass(frozen=True)
class CRMContext:
    text: str


class LocalCRM:
    def __init__(self, data_dir: Path, *, account_id: str = "local") -> None:
        self.data_dir = canonical_path(data_dir)
        self.account_id = safe_part(account_id)
        self.database_path = canonical_path(self.data_dir / "crm" / f"{self.account_id}.sqlite3")
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with _SCHEMA_INITIALIZATION_LOCK:
            if self.database_path not in _INITIALIZED_DATABASES:
                self._init_schema()
                _INITIALIZED_DATABASES.add(self.database_path)

    def note_interaction(
        self,
        *,
        agent_id: str,
        message: str,
        summary: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        client_name = extract_client_name(message)
        with self._connect() as db:
            client_id: int | None = None
            if client_name:
                row = db.execute(
                    "select id from clients where lower(name) = lower(?) limit 1",
                    (client_name,),
                ).fetchone()
                if row:
                    client_id = int(row["id"])
                else:
                    cursor = db.execute(
                        """
                        insert into clients(name, status, created_at, updated_at, metadata_json)
                        values (?, 'lead', ?, ?, '{}')
                        """,
                        (client_name, now_iso(), now_iso()),
                    )
                    client_id = int(cursor.lastrowid)
            db.execute(
                """
                insert into interactions(client_id, agent_id, channel, direction, summary, raw_text, created_at, metadata_json)
                values (?, ?, ?, 'inbound', ?, ?, ?, ?)
                """,
                (
                    client_id,
                    agent_id,
                    infer_channel(message),
                    redact_sensitive_text(summary[:1200]),
                    redact_sensitive_text(message[:3000]),
                    now_iso(),
                    json.dumps(metadata or {}, ensure_ascii=False),
                ),
            )
            db.execute(
                """
                delete from interactions
                where id < coalesce(
                    (select id from interactions order by id desc limit 1 offset ?),
                    0
                )
                """,
                (CRM_MAX_INTERACTIONS - 1,),
            )

    def context_for_query(self, query: str, *, max_chars: int = 2000) -> str:
        tokens = re.findall(r"[\wА-Яа-яЁё]{3,}", query.lower())
        with self._connect() as db:
            rows = db.execute(
                """
                select i.created_at, i.agent_id, i.channel, i.summary, c.name as client_name
                from interactions i
                left join clients c on c.id = i.client_id
                order by i.id desc
                limit 8
                """
            ).fetchall()
            deal_rows = db.execute(
                """
                select d.stage, d.title, d.value, d.currency, c.name as client_name
                from deals d
                left join clients c on c.id = d.client_id
                order by d.id desc
                limit 8
                """
            ).fetchall()
        if not rows and not deal_rows:
            return ""
        lines = ["Local CRM context:"]
        for row in rows:
            text = f"- {row['created_at']} {row['agent_id']} {row['channel']}"
            if row["client_name"]:
                text += f" client={row['client_name']}"
            text += f": {row['summary']}"
            if not tokens or any(token in text.lower() for token in tokens):
                lines.append(text)
        for row in deal_rows:
            text = f"- deal {row['stage']}: {row['title']}"
            if row["client_name"]:
                text += f" client={row['client_name']}"
            if row["value"]:
                text += f" value={row['value']} {row['currency']}"
            lines.append(text)
        output = "\n".join(lines)
        return output[:max_chars].rstrip()

    def _init_schema(self) -> None:
        with self._connect(configure_wal=True) as db:
            db.executescript(
                """
                create table if not exists clients (
                    id integer primary key autoincrement,
                    name text not null,
                    phone text not null default '',
                    email text not null default '',
                    source text not null default '',
                    status text not null default 'lead',
                    created_at text not null,
                    updated_at text not null,
                    metadata_json text not null default '{}'
                );
                create index if not exists ix_clients_status on clients(status, id);

                create table if not exists interactions (
                    id integer primary key autoincrement,
                    client_id integer,
                    agent_id text not null,
                    channel text not null default '',
                    direction text not null default '',
                    summary text not null default '',
                    raw_text text not null default '',
                    created_at text not null,
                    metadata_json text not null default '{}',
                    foreign key(client_id) references clients(id) on delete set null
                );
                create index if not exists ix_interactions_agent_id on interactions(agent_id, id);

                create table if not exists deals (
                    id integer primary key autoincrement,
                    client_id integer,
                    title text not null,
                    stage text not null default 'new',
                    value real,
                    currency text not null default 'USD',
                    created_at text not null,
                    updated_at text not null,
                    metadata_json text not null default '{}',
                    foreign key(client_id) references clients(id) on delete set null
                );

                create table if not exists notes (
                    id integer primary key autoincrement,
                    client_id integer,
                    agent_id text not null,
                    title text not null,
                    body text not null,
                    created_at text not null,
                    metadata_json text not null default '{}',
                    foreign key(client_id) references clients(id) on delete set null
                );
                """
            )

    @contextmanager
    def _connect(self, *, configure_wal: bool = False) -> Iterator[sqlite3.Connection]:
        connection: sqlite3.Connection | None = None
        try:
            connection = sqlite3.connect(self.database_path, timeout=10)
            connection.row_factory = sqlite3.Row
            connection.execute("pragma busy_timeout = 5000")
            connection.execute("pragma foreign_keys = on")
            if configure_wal:
                connection.execute("pragma journal_mode = wal")
            yield connection
            connection.commit()
        except Exception:
            if connection is not None:
                connection.rollback()
            raise
        finally:
            if connection is not None:
                connection.close()


def canonical_path(path: Path) -> Path:
    value = str(path.resolve(strict=False))
    if os.name == "nt":
        if value.startswith("\\\\?\\UNC\\"):
            value = "\\\\" + value[8:]
        elif value.startswith("\\\\?\\"):
            value = value[4:]
        value = os.path.normcase(value)
    return Path(value)


def safe_part(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", value.strip())[:80].strip(".-") or "local"


def extract_client_name(text: str) -> str:
    patterns = (
        r"(?:клиент|client)\s+([A-Za-zА-Яа-яЁё0-9_-]{2,40})",
        r"(?:имя|name)\s*[:=]\s*([A-Za-zА-Яа-яЁё0-9_-]{2,40})",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return match.group(1)
    return ""


def infer_channel(text: str) -> str:
    lowered = text.lower()
    if "direct" in lowered or "директ" in lowered or "dm" in lowered:
        return "direct"
    if "whatsapp" in lowered or "ватсап" in lowered:
        return "whatsapp"
    if "telegram" in lowered or "телеграм" in lowered:
        return "telegram"
    if "коммент" in lowered:
        return "comment"
    return "chat"


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")
