"""SQLite-адаптер аккаунтов и сессий. Схемой владеет Alembic."""
from __future__ import annotations

import contextlib
import os
import sqlite3
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from ragkb.features.chat_conversations.sqlite import EXPECTED_REVISION

COOKIE_NAME = "ragkb_session"
SESSION_DAYS = 7


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


class SqliteAccounts:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        _assert_revision(self.path)

    def create_user(self, username: str, password_hash: str) -> str:
        user_id = str(uuid.uuid4())
        now = utcnow().isoformat()
        with connect(self.path) as conn:
            conn.execute(
                "INSERT INTO users (id, username, password_hash, created_at)"
                " VALUES (?, ?, ?, ?)",
                (user_id, username, password_hash, now),
            )
        return user_id

    def get_by_username(self, username: str) -> tuple[str, str, str] | None:
        with connect(self.path) as conn:
            row = conn.execute(
                "SELECT id, username, password_hash FROM users WHERE username = ?",
                (username,),
            ).fetchone()
        if row is None:
            return None
        return (row["id"], row["username"], row["password_hash"])

    def create_session(self, user_id: str, token_hash: str, expires_at: str) -> None:
        with connect(self.path) as conn:
            conn.execute(
                "INSERT INTO sessions (token_hash, user_id, expires_at) VALUES (?, ?, ?)",
                (token_hash, user_id, expires_at),
            )

    def delete_session(self, token_hash: str) -> None:
        with connect(self.path) as conn:
            conn.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash,))

    def user_for_token_hash(self, token_hash: str) -> tuple[str, str] | None:
        now = utcnow().isoformat()
        with connect(self.path) as conn:
            row = conn.execute(
                "SELECT u.id, u.username FROM sessions s"
                " JOIN users u ON u.id = s.user_id"
                " WHERE s.token_hash = ? AND s.expires_at >= ?",
                (token_hash, now),
            ).fetchone()
        if row is None:
            return None
        return (row["id"], row["username"])
