from __future__ import annotations

import asyncio
from contextlib import contextmanager
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config as AlembicConfig
from fastapi.testclient import TestClient
from helpers import BACKEND_ROOT

from ragkb.app import create_app
from ragkb.core.config import Config, OrganizationConfig
from ragkb.core.database import make_engine, make_session_factory
from ragkb.db.repos.auth import PostgresAccounts
from ragkb.services.auth import hash_password


def _migrate_sqlite(url: str, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = AlembicConfig(str(BACKEND_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_ROOT / "migrations"))
    monkeypatch.setenv("RAGKB_DATABASE_URL", url)
    command.upgrade(cfg, "head")


async def _seed(url: str) -> None:
    engine = make_engine(url)
    accounts = PostgresAccounts(make_session_factory(engine))
    await accounts.ready()
    await accounts.create_user("ada", hash_password("password1"), role="admin")
    await accounts.create_user("bob", hash_password("password1"), role="user")
    await engine.dispose()


def _cfg(tmp_path: Path, url: str) -> Config:
    docs = tmp_path / "docs"
    docs.mkdir(exist_ok=True)
    cfg = Config(
        docs_dir=str(docs),
        index_dir=str(tmp_path / "index"),
        organization=OrganizationConfig(name="Acme", id="acme"),
    )
    cfg.store.backend = "numpy"
    cfg.database_url = url
    cfg.auth.mode = "session"
    cfg.history.enabled = True
    cfg.logging.dir = str(tmp_path / "logs")
    return cfg


@contextmanager
def _client(tmp_path: Path, url: str):
    with TestClient(create_app(_cfg(tmp_path, url))) as client:
        yield client


def _signin(client: TestClient, username: str, password: str = "password1") -> None:
    res = client.post(
        "/auth/signin",
        json={"username": username, "password": password},
    )
    assert res.status_code == 200


@pytest.fixture
def seeded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, str]:
    db = tmp_path / "ragkb.sqlite3"
    url = f"sqlite+aiosqlite:///{db}"
    _migrate_sqlite(url, monkeypatch)
    asyncio.run(_seed(url))
    return tmp_path, url


def test_profile_returns_details(seeded) -> None:
    tmp_path, url = seeded
    with _client(tmp_path, url) as client:
        _signin(client, "bob")
        res = client.get("/auth/profile")
        assert res.status_code == 200
        body = res.json()
        assert body["username"] == "bob"
        assert body["role"] == "user"
        assert body["created_at"] is not None


def test_profile_requires_session(seeded) -> None:
    tmp_path, url = seeded
    with _client(tmp_path, url) as client:
        res = client.get("/auth/profile")
        assert res.status_code == 401


def test_change_password_ok(seeded) -> None:
    tmp_path, url = seeded
    with _client(tmp_path, url) as client:
        _signin(client, "bob")
        res = client.post(
            "/auth/password",
            json={"current_password": "password1", "new_password": "new-pass1"},
        )
        assert res.status_code == 204
        # Старая сессия жива (текущая сохранена).
        assert client.get("/auth/me").status_code == 200
        # Старый пароль больше не подходит.
        client.post("/auth/signout")
        bad = client.post(
            "/auth/signin", json={"username": "bob", "password": "password1"}
        )
        assert bad.status_code == 401
        good = client.post(
            "/auth/signin", json={"username": "bob", "password": "new-pass1"}
        )
        assert good.status_code == 200


def test_change_password_other_sessions_invalidated(seeded) -> None:
    """Вторая сессия пользователя гаснет, текущая остаётся."""
    tmp_path, url = seeded
    with _client(tmp_path, url) as client:
        _signin(client, "bob")
        # Вторая «вкладка»: ещё одна сессия.
        second = TestClient(create_app(_cfg(tmp_path, url)))
        second.post(
            "/auth/signin",
            json={"username": "bob", "password": "password1"},
        )
        assert second.get("/auth/me").status_code == 200

        res = client.post(
            "/auth/password",
            json={"current_password": "password1", "new_password": "new-pass1"},
        )
        assert res.status_code == 204
        # Текущая сессия работает…
        assert client.get("/auth/me").status_code == 200
        # …а вторая — погашена.
        assert second.get("/auth/me").status_code == 401
        second.close()


def test_change_password_wrong_current_is_400(seeded) -> None:
    tmp_path, url = seeded
    with _client(tmp_path, url) as client:
        _signin(client, "bob")
        res = client.post(
            "/auth/password",
            json={"current_password": "wrong-pass", "new_password": "new-pass1"},
        )
        assert res.status_code == 400


def test_change_password_short_new_is_422(seeded) -> None:
    tmp_path, url = seeded
    with _client(tmp_path, url) as client:
        _signin(client, "bob")
        res = client.post(
            "/auth/password",
            json={"current_password": "password1", "new_password": "short"},
        )
        assert res.status_code == 422


def test_change_password_requires_session(seeded) -> None:
    tmp_path, url = seeded
    with _client(tmp_path, url) as client:
        res = client.post(
            "/auth/password",
            json={"current_password": "password1", "new_password": "new-pass1"},
        )
        assert res.status_code == 401


def test_proxy_mode_profile_and_password(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """В proxy-режиме профиль читается из заголовков, смена пароля запрещена."""
    db = tmp_path / "ragkb.sqlite3"
    url = f"sqlite+aiosqlite:///{db}"
    _migrate_sqlite(url, monkeypatch)
    cfg = _cfg(tmp_path, url)
    cfg.auth.mode = "proxy"
    with TestClient(create_app(cfg)) as client:
        headers = {"X-Forwarded-Preferred-Username": "ada"}
        res = client.get("/auth/profile", headers=headers)
        assert res.status_code == 200
        body = res.json()
        assert body["username"] == "ada"
        assert body["created_at"] is None
        res = client.post(
            "/auth/password",
            headers=headers,
            json={"current_password": "password1", "new_password": "new-pass1"},
        )
        assert res.status_code == 403
