from __future__ import annotations

import sqlite3
from pathlib import Path

from helpers import migrate


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
