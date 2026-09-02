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
from ragkb.db.repos.postgres_history import PostgresHistory
from ragkb.services.auth import hash_password


def _migrate_sqlite(url: str, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = AlembicConfig(str(BACKEND_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_ROOT / "migrations"))
    monkeypatch.setenv("RAGKB_DATABASE_URL", url)
    command.upgrade(cfg, "head")


async def _seed(url: str) -> tuple[str, int, str]:
    """ada-админ и bob; диалог ada с вопросом и ответом. Возвращает (cid, mid, question_id)."""
    engine = make_engine(url)
    accounts = PostgresAccounts(make_session_factory(engine))
    history = PostgresHistory(make_session_factory(engine))
    await accounts.ready()
    await accounts.create_user("ada", hash_password("password1"), role="admin")
    await accounts.create_user("bob", hash_password("password1"), role="user")
    cid = await history.create("ada")
    await history.append(cid, "ada", "user", "сколько длится отпуск?")
    mid = await history.append(cid, "ada", "assistant", "28 дней.")
    assert mid is not None
    await engine.dispose()
    return cid, mid


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
def _client(cfg: Config):
    with TestClient(create_app(cfg)) as client:
        yield client


def _signin(client: TestClient, username: str) -> None:
    res = client.post(
        "/auth/signin",
        json={"username": username, "password": "password1"},
    )
    assert res.status_code == 200


def _feedback_path(cid: str, mid: int) -> str:
    return (
        f"/organization/acme/chat_conversations/{cid}/messages/{mid}/feedback"
    )


@pytest.fixture
def seeded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[str, int, Path, str]:
    db = tmp_path / "ragkb.sqlite3"
    url = f"sqlite+aiosqlite:///{db}"
    _migrate_sqlite(url, monkeypatch)
    cid, mid = asyncio.run(_seed(url))
    return cid, mid, tmp_path, url


def test_owner_rates_answer(seeded) -> None:
    cid, mid, tmp_path, url = seeded
    with _client(_cfg(tmp_path, url)) as client:
        _signin(client, "ada")
        res = client.patch(_feedback_path(cid, mid), json={"rating": "up"})
        assert res.status_code == 204


def test_rereating_updates_instead_of_duplicating(seeded) -> None:
    cid, mid, tmp_path, url = seeded
    with _client(_cfg(tmp_path, url)) as client:
        _signin(client, "ada")
        assert client.patch(_feedback_path(cid, mid), json={"rating": "up"}).status_code == 204
        assert (
            client.patch(
                _feedback_path(cid, mid),
                json={"rating": "down", "comment": "не по делу"},
            ).status_code
            == 204
        )
        res = client.get("/admin/feedback")
        assert res.status_code == 200
        body = res.json()
        assert body["counts"] == {"up": 0, "down": 1}
        assert len(body["items"]) == 1
        item = body["items"][0]
        assert item["username"] == "ada"
        assert item["rating"] == "down"
        assert item["comment"] == "не по делу"
        assert item["conversation_id"] == cid
        assert item["answer"] == "28 дней."


def test_foreign_conversation_is_404(seeded) -> None:
    cid, mid, tmp_path, url = seeded
    with _client(_cfg(tmp_path, url)) as client:
        _signin(client, "bob")
        res = client.patch(_feedback_path(cid, mid), json={"rating": "up"})
        assert res.status_code == 404


def test_missing_message_is_404(seeded) -> None:
    _cid, mid, tmp_path, url = seeded
    cid = "00000000-0000-0000-0000-000000000000"
    with _client(_cfg(tmp_path, url)) as client:
        _signin(client, "ada")
        res = client.patch(_feedback_path(cid, mid), json={"rating": "up"})
        assert res.status_code == 404


def test_bad_rating_is_400(seeded) -> None:
    cid, mid, tmp_path, url = seeded
    with _client(_cfg(tmp_path, url)) as client:
        _signin(client, "ada")
        res = client.patch(_feedback_path(cid, mid), json={"rating": "meh"})
        assert res.status_code == 400


def test_long_comment_is_400(seeded) -> None:
    cid, mid, tmp_path, url = seeded
    with _client(_cfg(tmp_path, url)) as client:
        _signin(client, "ada")
        res = client.patch(
            _feedback_path(cid, mid),
            json={"rating": "up", "comment": "д" * 501},
        )
        assert res.status_code == 400


def test_plain_user_cannot_read_summary(seeded) -> None:
    cid, mid, tmp_path, url = seeded
    with _client(_cfg(tmp_path, url)) as client:
        _signin(client, "bob")
        assert client.patch(_feedback_path(cid, mid), json={"rating": "up"}).status_code == 404
        res = client.get("/admin/feedback")
        assert res.status_code == 403


def test_unauthorized_rating_is_401(seeded) -> None:
    cid, mid, tmp_path, url = seeded
    with _client(_cfg(tmp_path, url)) as client:
        res = client.patch(_feedback_path(cid, mid), json={"rating": "up"})
        assert res.status_code == 401
