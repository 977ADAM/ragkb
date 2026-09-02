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


class _FakeEngine:
    """Подставной движок: отвечает фиксированной строкой без поиска."""

    def __init__(self, answer: str = "Перегенерированный ответ.") -> None:
        self._answer = answer
        self.answered = 0

    def stats(self) -> dict:
        # Без реального индекса: доступность документов неизвестна.
        return {}

    def stream_answer(self, question, top_k=None, history=None, expand=False, model=None):
        self.answered += 1
        return [], iter([self._answer])


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
def _client(tmp_path: Path, url: str, engine: _FakeEngine | None = None):
    cfg = _cfg(tmp_path, url)
    app = create_app(cfg)
    if engine is not None:
        app.state.container._engine = engine
    with TestClient(app) as client:
        yield client


def _signin(client: TestClient, username: str) -> None:
    res = client.post(
        "/auth/signin",
        json={"username": username, "password": "password1"},
    )
    assert res.status_code == 200


def _messages(client: TestClient, cid: str) -> list[dict]:
    body = client.get(f"/organization/acme/chat_conversations/{cid}").json()
    return body["messages"]


def _ask(client: TestClient, cid: str, question: str, engine: _FakeEngine) -> int:
    with client.stream(
        "POST",
        f"/organization/acme/chat_conversations/{cid}/messages",
        json={"question": question},
    ) as resp:
        assert resp.status_code == 200
        import json

        raw = b"".join(resp.iter_bytes()).decode()
    lines = [json.loads(l) for l in raw.strip().splitlines() if l.strip()]
    assert lines[-1]["type"] == "done"
    assert lines[-1]["message_id"] is not None
    assert engine.answered >= 1
    return lines[-1]["message_id"]


@pytest.fixture
def seeded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, str]:
    db = tmp_path / "ragkb.sqlite3"
    url = f"sqlite+aiosqlite:///{db}"
    _migrate_sqlite(url, monkeypatch)
    asyncio.run(_seed(url))
    return tmp_path, url


def test_regenerate_replaces_last_answer(seeded) -> None:
    tmp_path, url = seeded
    engine = _FakeEngine()
    with _client(tmp_path, url, engine) as client:
        _signin(client, "ada")
        cid = client.post("/organization/acme/chat_conversations", json={}).json()[
            "conversation_id"
        ]
        mid1 = _ask(client, cid, "сколько дней отпуска?", engine)

        with client.stream(
            "POST",
            f"/organization/acme/chat_conversations/{cid}/messages/{mid1}/regenerate",
            json={},
        ) as resp:
            assert resp.status_code == 200
            import json

            raw = b"".join(resp.iter_bytes()).decode()
        lines = [json.loads(l) for l in raw.strip().splitlines() if l.strip()]
        done = lines[-1]
        assert done["type"] == "done"
        mid2 = done["message_id"]
        assert mid2 is not None and mid2 != mid1

        msgs = _messages(client, cid)
        assert [m["role"] for m in msgs] == ["user", "assistant"]
        assert msgs[-1]["id"] == mid2
        assert msgs[-1]["text"] == "Перегенерированный ответ."


def test_regenerate_non_last_answer_is_400(seeded) -> None:
    tmp_path, url = seeded
    engine = _FakeEngine()
    with _client(tmp_path, url, engine) as client:
        _signin(client, "ada")
        cid = client.post("/organization/acme/chat_conversations", json={}).json()[
            "conversation_id"
        ]
        mid1 = _ask(client, cid, "первый вопрос?", engine)
        mid2 = _ask(client, cid, "второй вопрос?", engine)
        assert mid1 != mid2
        res = client.post(
            f"/organization/acme/chat_conversations/{cid}/messages/{mid1}/regenerate",
            json={},
        )
        assert res.status_code == 400


def test_regenerate_foreign_dialog_is_404(seeded) -> None:
    tmp_path, url = seeded
    engine = _FakeEngine()
    with _client(tmp_path, url, engine) as client:
        _signin(client, "ada")
        cid = client.post("/organization/acme/chat_conversations", json={}).json()[
            "conversation_id"
        ]
        mid = _ask(client, cid, "вопрос?", engine)
        client.post("/auth/signout")

        _signin(client, "bob")
        res = client.post(
            f"/organization/acme/chat_conversations/{cid}/messages/{mid}/regenerate",
            json={},
        )
        assert res.status_code == 404


def test_remove_message_only_owner() -> None:
    import asyncio as _asyncio
    import os
    from ragkb.core.database import make_engine as _make_engine

    async def _run(url: str) -> None:
        store = PostgresHistory(make_session_factory(_make_engine(url)))
        await store.ready()
        ada_cid = await store.create("ada")
        await store.append(ada_cid, "ada", "user", "вопрос")
        mid = await store.append(ada_cid, "ada", "assistant", "ответ")
        assert mid is not None
        # Чужой не может удалить сообщение ada.
        assert not await store.remove_message(mid, "bob")
        # Владелец может.
        assert await store.remove_message(mid, "ada")
        msgs = await store.get_messages(ada_cid, "ada")
        assert [m.role for m in msgs] == ["user"]

    url = _migrate_fresh()
    _asyncio.run(_run(url))


def _migrate_fresh() -> str:
    import os
    import tempfile
    from pathlib import Path as _Path

    tmp = _Path(tempfile.mkdtemp())
    db = tmp / "t.sqlite3"
    url = f"sqlite+aiosqlite:///{db}"
    os.environ["RAGKB_DATABASE_URL"] = url
    cfg = AlembicConfig(str(BACKEND_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_ROOT / "migrations"))
    command.upgrade(cfg, "head")
    return url
