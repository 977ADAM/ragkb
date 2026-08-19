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


# ------------------------------------------------------------- хранилище

from ragkb.config import HistoryConfig
from ragkb.history import Conversation, HistoryStore, Message, make_title


def _store() -> HistoryStore:
    return HistoryStore(_fresh_db())


def test_history_config_defaults():
    cfg = HistoryConfig()
    assert cfg.enabled is True
    assert cfg.retention_days == 90
    assert cfg.window == 3


def test_config_exposes_history_section():
    from ragkb.config import Config
    cfg = Config.from_dict({"history": {"retention_days": 7, "window": 5}})
    assert cfg.history.retention_days == 7
    assert cfg.history.window == 5


def test_make_title_truncates_long_question():
    title = make_title("а" * 200)
    assert len(title) <= 60


def test_make_title_keeps_short_question():
    assert make_title("Сколько дней отпуска?") == "Сколько дней отпуска?"


def test_make_title_collapses_whitespace():
    assert make_title("  Сколько   дней\nотпуска? ") == "Сколько дней отпуска?"


def test_create_and_list_conversation():
    store = _store()
    cid = store.create_conversation("ivanov", "Отпуск")
    items = store.list_conversations("ivanov")
    assert len(items) == 1
    assert items[0].id == cid
    assert items[0].title == "Отпуск"


def test_conversations_of_other_user_are_invisible():
    store = _store()
    store.create_conversation("ivanov", "Отпуск")
    assert store.list_conversations("petrov") == []


def test_owns_is_false_for_other_user():
    store = _store()
    cid = store.create_conversation("ivanov", "Отпуск")
    assert store.owns(cid, "ivanov")
    assert not store.owns(cid, "petrov")


def test_append_and_read_messages():
    store = _store()
    cid = store.create_conversation("ivanov", "Отпуск")
    store.append(cid, "ivanov", "user", "Сколько дней?")
    store.append(cid, "ivanov", "assistant", "28 календарных дней [1].",
                 [{"n": 1, "citation": "Регламент", "source": "data/docs/o.md"}])
    messages = store.get_messages(cid, "ivanov")
    assert [m.role for m in messages] == ["user", "assistant"]
    assert messages[1].sources[0]["source"] == "data/docs/o.md"


def test_append_to_other_conversation_is_refused():
    store = _store()
    cid = store.create_conversation("ivanov", "Отпуск")
    assert store.append(cid, "petrov", "user", "чужое") is False
    assert store.get_messages(cid, "ivanov") == []


def test_get_messages_of_other_user_returns_none():
    store = _store()
    cid = store.create_conversation("ivanov", "Отпуск")
    store.append(cid, "ivanov", "user", "Сколько дней?")
    assert store.get_messages(cid, "petrov") is None


def test_get_messages_of_unknown_conversation_returns_none():
    assert _store().get_messages("нет-такого", "ivanov") is None


def test_recent_turns_pairs_question_and_answer():
    store = _store()
    cid = store.create_conversation("ivanov", "Отпуск")
    store.append(cid, "ivanov", "user", "в1")
    store.append(cid, "ivanov", "assistant", "о1")
    store.append(cid, "ivanov", "user", "в2")
    store.append(cid, "ivanov", "assistant", "о2")
    assert store.recent_turns(cid, "ivanov", window=3) == [("в1", "о1"), ("в2", "о2")]


def test_recent_turns_respects_window():
    store = _store()
    cid = store.create_conversation("ivanov", "Отпуск")
    for i in range(5):
        store.append(cid, "ivanov", "user", f"в{i}")
        store.append(cid, "ivanov", "assistant", f"о{i}")
    turns = store.recent_turns(cid, "ivanov", window=2)
    assert turns == [("в3", "о3"), ("в4", "о4")]


def test_recent_turns_drops_unanswered_question():
    store = _store()
    cid = store.create_conversation("ivanov", "Отпуск")
    store.append(cid, "ivanov", "user", "в1")
    store.append(cid, "ivanov", "assistant", "о1")
    store.append(cid, "ivanov", "user", "без ответа")
    assert store.recent_turns(cid, "ivanov", window=3) == [("в1", "о1")]


def test_recent_turns_for_other_user_is_empty():
    store = _store()
    cid = store.create_conversation("ivanov", "Отпуск")
    store.append(cid, "ivanov", "user", "в1")
    store.append(cid, "ivanov", "assistant", "о1")
    assert store.recent_turns(cid, "petrov", window=3) == []


def test_delete_removes_conversation_and_messages():
    store = _store()
    cid = store.create_conversation("ivanov", "Отпуск")
    store.append(cid, "ivanov", "user", "в1")
    assert store.delete_conversation(cid, "ivanov") is True
    assert store.list_conversations("ivanov") == []
    assert store.get_messages(cid, "ivanov") is None


def test_delete_of_other_user_is_refused():
    store = _store()
    cid = store.create_conversation("ivanov", "Отпуск")
    assert store.delete_conversation(cid, "petrov") is False
    assert len(store.list_conversations("ivanov")) == 1


def test_appending_touches_updated_at():
    store = _store()
    cid = store.create_conversation("ivanov", "Отпуск")
    before = store.list_conversations("ivanov")[0].updated_at
    store.append(cid, "ivanov", "user", "в1")
    after = store.list_conversations("ivanov")[0].updated_at
    assert after >= before


def test_list_puts_recent_first():
    store = _store()
    old = store.create_conversation("ivanov", "Старый")
    new = store.create_conversation("ivanov", "Новый")
    with connect(store.path) as conn:
        conn.execute("UPDATE conversations SET updated_at = ? WHERE id = ?",
                     ("2020-01-01T00:00:00+00:00", old))
    assert [c.id for c in store.list_conversations("ivanov")] == [new, old]


# --------------------------------------------------------------- уборка

import threading
from datetime import timedelta


def test_cleanup_removes_expired():
    store = HistoryStore(_fresh_db(), retention_days=30)
    old = store.create_conversation("ivanov", "Старый")
    with connect(store.path) as conn:
        conn.execute("UPDATE conversations SET updated_at = ? WHERE id = ?",
                     ((utcnow() - timedelta(days=60)).isoformat(), old))
    assert store.cleanup() == 1
    assert store.list_conversations("ivanov") == []


def test_cleanup_keeps_fresh():
    store = HistoryStore(_fresh_db(), retention_days=30)
    store.create_conversation("ivanov", "Свежий")
    assert store.cleanup() == 0
    assert len(store.list_conversations("ivanov")) == 1


def test_cleanup_removes_messages_of_expired():
    store = HistoryStore(_fresh_db(), retention_days=30)
    old = store.create_conversation("ivanov", "Старый")
    store.append(old, "ivanov", "user", "в1")
    with connect(store.path) as conn:
        conn.execute("UPDATE conversations SET updated_at = ? WHERE id = ?",
                     ((utcnow() - timedelta(days=60)).isoformat(), old))
    store.cleanup()
    with connect(store.path) as conn:
        assert conn.execute("SELECT count(*) FROM messages").fetchone()[0] == 0


def test_cleanup_does_not_repeat_within_a_day():
    store = HistoryStore(_fresh_db(), retention_days=30)
    for _ in range(2):
        cid = store.create_conversation("ivanov", "Старый")
        with connect(store.path) as conn:
            conn.execute("UPDATE conversations SET updated_at = ? WHERE id = ?",
                         ((utcnow() - timedelta(days=60)).isoformat(), cid))
    assert store.cleanup() == 2
    # Второй вызов подряд не должен ничего делать: сутки не прошли.
    cid = store.create_conversation("ivanov", "Ещё старый")
    with connect(store.path) as conn:
        conn.execute("UPDATE conversations SET updated_at = ? WHERE id = ?",
                     ((utcnow() - timedelta(days=60)).isoformat(), cid))
    assert store.cleanup() == 0
    assert len(store.list_conversations("ivanov")) == 1


def test_cleanup_runs_again_after_a_day():
    store = HistoryStore(_fresh_db(), retention_days=30)
    assert store.cleanup() == 0
    cid = store.create_conversation("ivanov", "Старый")
    with connect(store.path) as conn:
        conn.execute("UPDATE conversations SET updated_at = ? WHERE id = ?",
                     ((utcnow() - timedelta(days=60)).isoformat(), cid))
    # Сутки спустя отметка снова просрочена.
    assert store.cleanup(now=utcnow() + timedelta(days=2)) == 1


def test_cleanup_is_limited_by_batch():
    store = HistoryStore(_fresh_db(), retention_days=30)
    stale = (utcnow() - timedelta(days=60)).isoformat()
    for _ in range(5):
        cid = store.create_conversation("ivanov", "Старый")
        with connect(store.path) as conn:
            conn.execute("UPDATE conversations SET updated_at = ? WHERE id = ?",
                         (stale, cid))
    assert store.cleanup(batch=2) == 2
    assert len(store.list_conversations("ivanov")) == 3


def test_concurrent_cleanup_runs_once():
    store = HistoryStore(_fresh_db(), retention_days=30)
    stale = (utcnow() - timedelta(days=60)).isoformat()
    for _ in range(4):
        cid = store.create_conversation("ivanov", "Старый")
        with connect(store.path) as conn:
            conn.execute("UPDATE conversations SET updated_at = ? WHERE id = ?",
                         (stale, cid))
    results: list[int] = []
    lock = threading.Lock()

    def run():
        removed = store.cleanup()
        with lock:
            results.append(removed)

    threads = [threading.Thread(target=run) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    # Отметка обновляется атомарно: уборку выполняет ровно один из двух.
    assert sorted(results) == [0, 4], results


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
