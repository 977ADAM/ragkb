"""Тесты хранилища диалогов. Запуск: python tests/test_history.py"""
from __future__ import annotations

import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ragkb.history import SCHEMA_VERSION, connect, init_schema, utcnow


def _fresh_db() -> Path:
    """Пустая база во временном каталоге. Не :memory: — там WAL недоступен."""
    return Path(tempfile.mkdtemp(prefix="ragkb-history-")) / "history.sqlite3"


# --------------------------------------------------------------- соединение

def test_foreign_keys_are_enabled():
    with connect(_fresh_db()) as conn:
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1


def test_journal_mode_is_wal():
    with connect(_fresh_db()) as conn:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"


def test_busy_timeout_is_set():
    with connect(_fresh_db()) as conn:
        assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == 5000


def test_rows_are_accessible_by_name():
    path = _fresh_db()
    with connect(path) as conn:
        init_schema(conn)
        conn.execute(
            "INSERT INTO conversations (id, user, title, created_at, updated_at)"
            " VALUES ('c1', 'ivanov', 'тема', '2026-01-01T00:00:00+00:00',"
            " '2026-01-01T00:00:00+00:00')"
        )
    with connect(path) as conn:
        row = conn.execute("SELECT title FROM conversations").fetchone()
        assert row["title"] == "тема"


# -------------------------------------------------------------------- схема

def test_init_schema_sets_user_version():
    path = _fresh_db()
    with connect(path) as conn:
        init_schema(conn)
        assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION


def test_init_schema_is_idempotent():
    path = _fresh_db()
    with connect(path) as conn:
        init_schema(conn)
        init_schema(conn)
        names = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        assert {"conversations", "messages", "cleanup_state"} <= names


def test_cascade_removes_messages():
    path = _fresh_db()
    with connect(path) as conn:
        init_schema(conn)
        conn.execute(
            "INSERT INTO conversations (id, user, title, created_at, updated_at)"
            " VALUES ('c1', 'ivanov', 'тема', '2026-01-01T00:00:00+00:00',"
            " '2026-01-01T00:00:00+00:00')"
        )
        conn.execute(
            "INSERT INTO messages (conversation_id, role, text, created_at)"
            " VALUES ('c1', 'user', 'вопрос', '2026-01-01T00:00:00+00:00')"
        )
        conn.execute("DELETE FROM conversations WHERE id = 'c1'")
        assert conn.execute("SELECT count(*) FROM messages").fetchone()[0] == 0


def test_role_is_constrained():
    path = _fresh_db()
    with connect(path) as conn:
        init_schema(conn)
        conn.execute(
            "INSERT INTO conversations (id, user, title, created_at, updated_at)"
            " VALUES ('c1', 'ivanov', 'тема', '2026-01-01T00:00:00+00:00',"
            " '2026-01-01T00:00:00+00:00')"
        )
        try:
            conn.execute(
                "INSERT INTO messages (conversation_id, role, text, created_at)"
                " VALUES ('c1', 'система', 'нельзя', '2026-01-01T00:00:00+00:00')"
            )
        except sqlite3.IntegrityError:
            return
        raise AssertionError("ожидалось нарушение CHECK по роли")


def test_newer_schema_version_is_refused():
    path = _fresh_db()
    with connect(path) as conn:
        init_schema(conn)
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION + 1}")
    with connect(path) as conn:
        try:
            init_schema(conn)
        except RuntimeError as exc:
            assert str(SCHEMA_VERSION + 1) in str(exc), str(exc)
            return
        raise AssertionError("ожидался отказ работать со схемой из будущего")


def test_utcnow_is_timezone_aware():
    assert utcnow().tzinfo is not None


if __name__ == "__main__":
    failed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"  ok   {name}")
            except Exception as exc:
                failed += 1
                print(f"  FAIL {name}: {type(exc).__name__}: {exc}")
    print(f"\n{'все тесты пройдены' if not failed else f'провалов: {failed}'}")
    raise SystemExit(1 if failed else 0)
