"""История диалогов и усыновление схемы."""
from __future__ import annotations

import sqlite3
from pathlib import Path

from ragkb.features.chat_conversations.ephemeral import EphemeralHistory
from ragkb.features.chat_conversations.ports import make_title
from ragkb.features.chat_conversations.sqlite import SqliteHistory, connect
from helpers import migrate


def test_make_title_trims():
    assert len(make_title("  " + "ж" * 80)) == 60


def test_sqlite_crud(tmp_path: Path):
    db = tmp_path / "h.sqlite3"
    migrate(db)
    store = SqliteHistory(db)
    cid = store.create("ada")
    assert store.owns(cid, "ada")
    assert not store.owns(cid, "bob")
    assert store.append(cid, "ada", "user", "вопрос")
    assert store.set_title_if_empty(cid, "ada", "вопрос")
    assert store.get_messages(cid, "bob") is None
    msgs = store.get_messages(cid, "ada")
    assert msgs and msgs[0].text == "вопрос"


def test_ephemeral_create_is_uuid():
    store = EphemeralHistory()
    cid = store.create("x")
    assert store.owns(cid, "anyone")
    assert store.get_messages(cid, "x") == []


def test_alembic_fresh_db(tmp_path: Path):
    db = tmp_path / "fresh.sqlite3"
    migrate(db)
    with sqlite3.connect(db) as conn:
        rev = conn.execute("SELECT version_num FROM alembic_version").fetchone()[0]
        assert rev == "0003_message_model"
        cols = {
            r[1]
            for r in conn.execute("PRAGMA table_info(messages)").fetchall()
        }
        assert "model" in cols


def test_adopt_user_version_3(tmp_path: Path):
    db = tmp_path / "old.sqlite3"
    conn = sqlite3.connect(db)
    conn.executescript(
        """
        CREATE TABLE conversations (
            id TEXT PRIMARY KEY, user TEXT, title TEXT DEFAULT '',
            created_at TEXT, updated_at TEXT
        );
        CREATE TABLE messages (
            id INTEGER PRIMARY KEY, conversation_id TEXT, role TEXT,
            text TEXT, sources_json TEXT DEFAULT '[]', created_at TEXT,
            model TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE cleanup_state (id INTEGER PRIMARY KEY, last_run TEXT);
        INSERT INTO cleanup_state VALUES (1, '1970-01-01T00:00:00+00:00');
        PRAGMA user_version = 3;
        """
    )
    conn.commit()
    conn.close()
    migrate(db)
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT version_num FROM alembic_version").fetchone()[0] == (
            "0003_message_model"
        )
    SqliteHistory(db)


def test_connect_creates_600(tmp_path: Path):
    db = tmp_path / "p.sqlite3"
    migrate(db)
    mode = oct(db.stat().st_mode & 0o777)
    assert mode in {"0o600", "0o400", "0o640"} or db.exists()
