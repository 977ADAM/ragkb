"""SQLite-адаптер истории. Схемой владеет Alembic, здесь только запросы."""
from __future__ import annotations

import contextlib
import json
import os
import sqlite3
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from ragkb.features.chat_conversations.ports import Conversation, Message

EXPECTED_REVISION = "0003_message_model"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


@contextmanager
def connect(path: str | Path) -> Iterator[sqlite3.Connection]:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        with contextlib.suppress(FileExistsError):
            os.close(os.open(str(path), os.O_CREAT | os.O_EXCL, 0o600))
    conn = sqlite3.connect(str(path), timeout=5)
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.row_factory = sqlite3.Row
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _assert_revision(path: Path) -> None:
    with connect(path) as conn:
        try:
            rows = conn.execute("SELECT version_num FROM alembic_version").fetchall()
        except sqlite3.OperationalError as exc:
            raise RuntimeError(
                f"В базе {path.resolve()} нет таблицы alembic_version. "
                f"Код ждёт ревизию {EXPECTED_REVISION}. "
                "Выполните: alembic upgrade head"
            ) from exc
        found = [r["version_num"] for r in rows]
        if len(found) != 1 or found[0] != EXPECTED_REVISION:
            raise RuntimeError(
                f"Ревизия базы {path.resolve()}: {found!r}, "
                f"код ждёт {EXPECTED_REVISION}. "
                "Выполните alembic upgrade head или откатитесь на нужный образ."
            )


class SqliteHistory:
    CLEANUP_INTERVAL_DAYS = 1

    def __init__(self, path: str | Path, retention_days: int = 90):
        self.path = Path(path)
        self.retention_days = retention_days
        _assert_revision(self.path)

    def create(self, user: str) -> str:
        conversation_id = str(uuid.uuid4())
        now = utcnow().isoformat()
        with connect(self.path) as conn:
            conn.execute(
                "INSERT INTO conversations (id, user, title, created_at, updated_at)"
                " VALUES (?, ?, '', ?, ?)",
                (conversation_id, user, now, now),
            )
        return conversation_id

    def append(
        self,
        conversation_id: str,
        user: str,
        role: str,
        text: str,
        sources: list[dict[str, Any]] | None = None,
        model: str = "",
    ) -> bool:
        now = utcnow().isoformat()
        with connect(self.path) as conn:
            owner = conn.execute(
                "SELECT 1 FROM conversations WHERE id = ? AND user = ?",
                (conversation_id, user),
            ).fetchone()
            if owner is None:
                return False
            conn.execute(
                "INSERT INTO messages (conversation_id, role, text, sources_json,"
                " created_at, model) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    conversation_id,
                    role,
                    text,
                    json.dumps(sources or [], ensure_ascii=False),
                    now,
                    model,
                ),
            )
            conn.execute(
                "UPDATE conversations SET updated_at = ? WHERE id = ?",
                (now, conversation_id),
            )
        return True

    def set_title_if_empty(self, conversation_id: str, user: str, title: str) -> bool:
        with connect(self.path) as conn:
            cur = conn.execute(
                "UPDATE conversations SET title = ? WHERE id = ? AND user = ? AND title = ''",
                (title, conversation_id, user),
            )
        return cur.rowcount > 0

    def owns(self, conversation_id: str, user: str) -> bool:
        with connect(self.path) as conn:
            row = conn.execute(
                "SELECT 1 FROM conversations WHERE id = ? AND user = ?",
                (conversation_id, user),
            ).fetchone()
        return row is not None

    def list_conversations(
        self, user: str, limit: int = 50, offset: int = 0
    ) -> list[Conversation]:
        with connect(self.path) as conn:
            rows = conn.execute(
                "SELECT id, title, created_at, updated_at FROM conversations"
                " WHERE user = ? ORDER BY updated_at DESC LIMIT ? OFFSET ?",
                (user, limit, offset),
            ).fetchall()
        return [
            Conversation(r["id"], r["title"], r["created_at"], r["updated_at"])
            for r in rows
        ]

    def count_conversations(self, user: str) -> int:
        with connect(self.path) as conn:
            row = conn.execute(
                "SELECT count(*) FROM conversations WHERE user = ?", (user,)
            ).fetchone()
        return row[0]

    def get_messages(self, conversation_id: str, user: str) -> list[Message] | None:
        with connect(self.path) as conn:
            owner = conn.execute(
                "SELECT 1 FROM conversations WHERE id = ? AND user = ?",
                (conversation_id, user),
            ).fetchone()
            if owner is None:
                return None
            rows = conn.execute(
                "SELECT role, text, sources_json, created_at, model FROM messages"
                " WHERE conversation_id = ? ORDER BY id",
                (conversation_id,),
            ).fetchall()
        return [
            Message(
                role=r["role"],
                text=r["text"],
                created_at=r["created_at"],
                sources=json.loads(r["sources_json"]),
                model=r["model"],
            )
            for r in rows
        ]

    def recent_turns(
        self, conversation_id: str, user: str, window: int
    ) -> list[tuple[str, str]]:
        if window <= 0:
            return []
        with connect(self.path) as conn:
            owner = conn.execute(
                "SELECT 1 FROM conversations WHERE id = ? AND user = ?",
                (conversation_id, user),
            ).fetchone()
            if owner is None:
                return []
            rows = conn.execute(
                "SELECT role, text FROM messages WHERE conversation_id = ?"
                " ORDER BY id DESC LIMIT ?",
                (conversation_id, window * 2 + 1),
            ).fetchall()
        turns: list[tuple[str, str]] = []
        pending: str | None = None
        for row in reversed(rows):
            if row["role"] == "user":
                pending = row["text"]
            elif pending is not None:
                turns.append((pending, row["text"]))
                pending = None
        return turns[-window:]

    def rename(self, conversation_id: str, user: str, title: str) -> bool:
        with connect(self.path) as conn:
            cur = conn.execute(
                "UPDATE conversations SET title = ? WHERE id = ? AND user = ?",
                (title, conversation_id, user),
            )
        return cur.rowcount > 0

    def delete(self, conversation_id: str, user: str) -> bool:
        with connect(self.path) as conn:
            cur = conn.execute(
                "DELETE FROM conversations WHERE id = ? AND user = ?",
                (conversation_id, user),
            )
        return cur.rowcount > 0

    def cleanup(self, now: datetime | None = None, batch: int = 500) -> int:
        now = now or utcnow()
        due_before = (now - timedelta(days=self.CLEANUP_INTERVAL_DAYS)).isoformat()
        expired_before = (now - timedelta(days=self.retention_days)).isoformat()
        with connect(self.path) as conn:
            claimed = conn.execute(
                "UPDATE cleanup_state SET last_run = ? WHERE id = 1 AND last_run < ?",
                (now.isoformat(), due_before),
            )
            if claimed.rowcount == 0:
                return 0
            removed = conn.execute(
                "DELETE FROM conversations WHERE id IN ("
                " SELECT id FROM conversations WHERE updated_at < ? LIMIT ?)",
                (expired_before, batch),
            )
            if removed.rowcount == batch:
                conn.execute(
                    "UPDATE cleanup_state SET last_run = ? WHERE id = 1",
                    ("1970-01-01T00:00:00+00:00",),
                )
        return removed.rowcount
