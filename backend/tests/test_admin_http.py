from __future__ import annotations

import asyncio
from contextlib import contextmanager
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config as AlembicConfig
from fastapi.testclient import TestClient
from helpers import BACKEND_ROOT

from ragkb.core.config import Config, OrganizationConfig
from ragkb.db.repos.auth import PostgresAccounts
from ragkb.app import create_app
from ragkb.core.database import make_engine, make_session_factory
from ragkb.services.auth import hash_password


def _migrate_sqlite(url: str, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = AlembicConfig(str(BACKEND_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_ROOT / "migrations"))
    monkeypatch.setenv("RAGKB_DATABASE_URL", url)
    command.upgrade(cfg, "head")


async def _seed_admin_and_user(url: str) -> None:
    engine = make_engine(url)
    store = PostgresAccounts(make_session_factory(engine))
    await store.ready()
    await store.create_user("ada", hash_password("password1"), role="admin")
    await store.create_user("bob", hash_password("password1"), role="user")
    await engine.dispose()


def _session_cfg(tmp_path: Path, url: str, org: OrganizationConfig | None = None) -> Config:
    docs = tmp_path / "docs"
    docs.mkdir(exist_ok=True)
    cfg = Config(
        docs_dir=str(docs),
        index_dir=str(tmp_path / "index"),
        organization=org or OrganizationConfig(name="Acme", id="acme"),
    )
    cfg.store.backend = "numpy"
    cfg.database_url = url
    cfg.auth.mode = "session"
    cfg.history.enabled = True
    cfg.logging.dir = str(tmp_path / "logs")
    return cfg


@contextmanager
def _admin_client(cfg: Config):
    with TestClient(create_app(cfg)) as client:
        yield client


def _signin(client: TestClient, username: str) -> None:
    res = client.post(
        "/auth/signin",
        json={"username": username, "password": "password1"},
    )
    assert res.status_code == 200


@pytest.fixture
def sqlite_url(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    db = tmp_path / "ragkb.sqlite3"
    url = f"sqlite+aiosqlite:///{db}"
    _migrate_sqlite(url, monkeypatch)
    asyncio.run(_seed_admin_and_user(url))
    return url


def test_plain_user_cannot_list_admin_users(
    tmp_path: Path, sqlite_url: str
) -> None:
    with _admin_client(_session_cfg(tmp_path, sqlite_url)) as client:
        _signin(client, "bob")
        res = client.get("/admin/users")
        assert res.status_code == 403


def test_admin_lists_users(tmp_path: Path, sqlite_url: str) -> None:
    with _admin_client(_session_cfg(tmp_path, sqlite_url)) as client:
        _signin(client, "ada")
        res = client.get("/admin/users")
        assert res.status_code == 200
        users = {(u["username"], u["role"]) for u in res.json()["users"]}
        assert ("ada", "admin") in users
        assert ("bob", "user") in users
        for row in res.json()["users"]:
            assert "created_at" in row


def test_cannot_demote_last_admin(tmp_path: Path, sqlite_url: str) -> None:
    with _admin_client(_session_cfg(tmp_path, sqlite_url)) as client:
        _signin(client, "ada")
        res = client.patch("/admin/users/ada", json={"role": "user"})
        assert res.status_code == 403
        assert res.json()["detail"] == "нельзя разжаловать последнего админа"


def test_cannot_delete_self(tmp_path: Path, sqlite_url: str) -> None:
    with _admin_client(_session_cfg(tmp_path, sqlite_url)) as client:
        _signin(client, "ada")
        res = client.delete("/admin/users/ada")
        assert res.status_code == 403
        assert res.json()["detail"] == "нельзя удалить себя"


def test_patch_missing_user_is_404(tmp_path: Path, sqlite_url: str) -> None:
    with _admin_client(_session_cfg(tmp_path, sqlite_url)) as client:
        _signin(client, "ada")
        res = client.patch("/admin/users/nobody", json={"role": "admin"})
        assert res.status_code == 404


def test_reports_unavailable(tmp_path: Path, sqlite_url: str) -> None:
    with _admin_client(_session_cfg(tmp_path, sqlite_url)) as client:
        _signin(client, "ada")
        res = client.get("/admin/reports")
        assert res.status_code == 200
        assert res.json() == {"status": "unavailable"}


def test_organization_hub_from_config(tmp_path: Path, sqlite_url: str) -> None:
    with _admin_client(_session_cfg(tmp_path, sqlite_url)) as client:
        _signin(client, "ada")
        res = client.get("/admin/organization")
        assert res.status_code == 200
        body = res.json()
        assert body["name"] == "Acme"
        assert body["id"] == "acme"
        assert body["links"] == {
            "users": "/admin/users",
            "reports": "/admin/reports",
            "feedback": "/admin/feedback",
        }


def test_organization_hub_empty_when_unconfigured(
    tmp_path: Path, sqlite_url: str
) -> None:
    cfg = _session_cfg(
        tmp_path,
        sqlite_url,
        org=OrganizationConfig(name="", id="", description=""),
    )
    with _admin_client(cfg) as client:
        _signin(client, "ada")
        res = client.get("/admin/organization")
        assert res.status_code == 200
        body = res.json()
        assert body["name"] == ""
        assert body["id"] == ""
        assert body["description"] == ""
        assert body["links"] == {
            "users": "/admin/users",
            "reports": "/admin/reports",
            "feedback": "/admin/feedback",
        }
