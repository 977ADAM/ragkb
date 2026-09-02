from __future__ import annotations

import uuid

import pytest

from ragkb.db.repos.auth import PostgresAccounts
from ragkb.core.database import make_engine, make_session_factory
from ragkb.services.auth import hash_password, verify_password


class _FakeStore:
    def __init__(self) -> None:
        self.users: dict[str, list[str]] = {}

    async def create_user(
        self, username: str, password_hash: str, role: str = "user"
    ) -> str:
        user_id = str(uuid.uuid4())
        self.users[username] = [user_id, username, password_hash, role]
        return user_id

    async def get_by_username(self, username: str) -> tuple[str, str, str, str] | None:
        row = self.users.get(username)
        if row is None:
            return None
        return (row[0], row[1], row[2], row[3])

    async def update_password(self, username: str, password_hash: str) -> None:
        self.users[username][2] = password_hash


@pytest.mark.asyncio
async def test_ensure_admin_skips_when_credentials_missing(monkeypatch, caplog):
    monkeypatch.delenv("ADMIN_LOGIN", raising=False)
    monkeypatch.delenv("ADMIN_PASSWORD", raising=False)
    from scripts.ensure_admin import ensure_admin

    store = _FakeStore()
    with caplog.at_level("WARNING"):
        await ensure_admin(store)
    assert store.users == {}


@pytest.mark.asyncio
async def test_ensure_admin_creates_then_idempotent_then_updates_hash(
    monkeypatch, caplog
):
    monkeypatch.setenv("ADMIN_LOGIN", "Ada")
    monkeypatch.setenv("ADMIN_PASSWORD", "password1")
    from scripts.ensure_admin import ensure_admin

    store = _FakeStore()
    with caplog.at_level("INFO"):
        await ensure_admin(store)
    assert "Admin created by system at" in caplog.text
    row = await store.get_by_username("ada")
    assert row is not None
    assert row[3] == "admin"
    first_hash = row[2]
    assert verify_password("password1", first_hash)

    await ensure_admin(store)
    same = await store.get_by_username("ada")
    assert same is not None
    assert same[2] == first_hash

    monkeypatch.setenv("ADMIN_PASSWORD", "password2")
    await ensure_admin(store)
    updated = await store.get_by_username("ada")
    assert updated is not None
    assert updated[2] != first_hash
    assert verify_password("password2", updated[2])


@pytest.mark.asyncio
async def test_update_password_persists(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    from alembic import command
    from alembic.config import Config as AlembicConfig
    from helpers import BACKEND_ROOT

    monkeypatch.delenv("RAGKB_TEST_DATABASE_URL", raising=False)
    db = tmp_path / "ragkb.sqlite3"
    url = f"sqlite+aiosqlite:///{db}"
    cfg = AlembicConfig(str(BACKEND_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_ROOT / "migrations"))
    monkeypatch.setenv("RAGKB_DATABASE_URL", url)
    command.upgrade(cfg, "head")
    engine = make_engine(url)
    store = PostgresAccounts(make_session_factory(engine))
    await store.ready()
    await store.create_user("ada", hash_password("password1"), role="admin")
    new_hash = hash_password("password2")
    await store.update_password("ada", new_hash)
    row = await store.get_by_username("ada")
    assert row is not None
    assert row[2] == new_hash
    await engine.dispose()
