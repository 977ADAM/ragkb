from __future__ import annotations

import sqlite3
from pathlib import Path

from helpers import migrate

from ragkb.features.auth.passwords import hash_password, verify_password
from ragkb.features.auth.sqlite import SqliteAccounts


def test_migrate_creates_users_and_sessions(tmp_path: Path) -> None:
    db = tmp_path / "h.sqlite3"
    migrate(db)
    conn = sqlite3.connect(str(db))
    names = {
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    assert "users" in names
    assert "sessions" in names
    rev = conn.execute("SELECT version_num FROM alembic_version").fetchone()[0]
    assert rev == "0004_users_sessions"


def test_password_roundtrip() -> None:
    hashed = hash_password("correct-horse")
    assert hashed != "correct-horse"
    assert verify_password("correct-horse", hashed)
    assert not verify_password("wrong", hashed)


def test_accounts_user_and_session(tmp_path: Path) -> None:
    db = tmp_path / "h.sqlite3"
    migrate(db)
    store = SqliteAccounts(db)
    uid = store.create_user("ada", hash_password("password1"))
    row = store.get_by_username("ada")
    assert row is not None
    assert row[0] == uid
    store.create_session(uid, "hash1", "2099-01-01T00:00:00+00:00")
    assert store.user_for_token_hash("hash1") == (uid, "ada")
    store.create_session(uid, "old", "2000-01-01T00:00:00+00:00")
    assert store.user_for_token_hash("old") is None
    store.delete_session("hash1")
    assert store.user_for_token_hash("hash1") is None
