from __future__ import annotations

import uuid
from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient
from helpers import alembic_sync_url, database_url, migrate
from sqlalchemy import create_engine, select, text

from ragkb.db.models import UserRow
from ragkb.db.repos.auth import PostgresAccounts
from ragkb.app import create_app
from ragkb.core.database import EXPECTED_REVISION, make_engine, make_session_factory
from ragkb.services.auth import hash_password, verify_password


@pytest.mark.asyncio
async def test_models_roundtrip_user() -> None:
    migrate()
    engine = make_engine(database_url())
    factory = make_session_factory(engine)
    async with factory() as session:
        prior = (
            await session.execute(
                select(UserRow).where(
                    (UserRow.id == "11111111-1111-4111-8111-111111111111")
                    | (UserRow.username == "ada")
                )
            )
        ).scalars().all()
        for row in prior:
            await session.delete(row)
        if prior:
            await session.commit()
        session.add(
            UserRow(
                id="11111111-1111-4111-8111-111111111111",
                username="ada",
                password_hash="x",
            )
        )
        await session.commit()
        row = (
            await session.execute(select(UserRow).where(UserRow.username == "ada"))
        ).scalar_one()
        assert row.username == "ada"
    await engine.dispose()


def test_migrate_creates_postgres_tables() -> None:
    migrate()
    engine = create_engine(alembic_sync_url(database_url()))
    with engine.connect() as conn:
        names = {
            r[0]
            for r in conn.execute(
                text(
                    "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
                )
            )
        }
        assert "users" in names
        assert "sessions" in names
        assert "conversations" in names
        assert "messages" in names
        rev = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
        assert rev == EXPECTED_REVISION
        owner = conn.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'conversations' AND column_name = 'owner'"
            )
        ).scalar()
        assert owner == "owner"


def test_password_roundtrip() -> None:
    hashed = hash_password("correct-horse")
    assert hashed != "correct-horse"
    assert verify_password("correct-horse", hashed)
    assert not verify_password("wrong", hashed)


@pytest.mark.asyncio
async def test_accounts_user_and_session() -> None:
    migrate()
    engine = make_engine(database_url())
    store = PostgresAccounts(make_session_factory(engine))
    await store.ready()
    username = f"acct-ada-{uuid.uuid4().hex[:12]}"
    uid = await store.create_user(username, hash_password("password1"))
    row = await store.get_by_username(username)
    assert row is not None
    assert row[0] == uid
    live_hash = f"hash1-{uuid.uuid4().hex}"
    expired_hash = f"old-{uuid.uuid4().hex}"
    await store.create_session(uid, live_hash, "2099-01-01T00:00:00+00:00")
    assert await store.user_for_token_hash(live_hash) == (uid, username, "user")
    await store.create_session(uid, expired_hash, "2000-01-01T00:00:00+00:00")
    assert await store.user_for_token_hash(expired_hash) is None
    await store.delete_session(live_hash)
    assert await store.user_for_token_hash(live_hash) is None
    await engine.dispose()


@pytest.mark.asyncio
async def test_create_user_default_role_user(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from alembic import command
    from alembic.config import Config as AlembicConfig
    from helpers import BACKEND_ROOT

    db = tmp_path / "ragkb.sqlite3"
    url = f"sqlite+aiosqlite:///{db}"
    cfg = AlembicConfig(str(BACKEND_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_ROOT / "migrations"))
    monkeypatch.setenv("RAGKB_DATABASE_URL", url)
    command.upgrade(cfg, "head")
    engine = make_engine(url)
    store = PostgresAccounts(make_session_factory(engine))
    await store.ready()
    uid = await store.create_user("ada", hash_password("password1"))
    row = await store.get_by_username("ada")
    assert row is not None
    assert row[0] == uid
    assert row[-1] == "user"
    listed = await store.list_users()
    assert [(name, role) for name, role, _created in listed] == [("ada", "user")]
    promoted = await store.set_role("ada", "admin")
    assert promoted is not None
    assert promoted[0] == "ada"
    assert promoted[1] == "admin"
    assert await store.count_admins() == 1
    assert await store.set_role("nobody", "admin") is None
    assert await store.delete_user("ada") is True
    assert await store.get_by_username("ada") is None
    assert await store.delete_user("ada") is False
    assert await store.count_admins() == 0
    await engine.dispose()


@contextmanager
def _session_client(cfg):
    cfg.database_url = database_url()
    cfg.auth.mode = "session"
    cfg.history.enabled = True
    with TestClient(create_app(cfg)) as client:
        yield client


def test_register_login_me_logout_bootstrap(indexed):
    with _session_client(indexed) as client:
        r = client.post(
            "/auth/signup",
            json={"username": "Ada", "password": "password1"},
        )
        assert r.status_code == 200
        assert r.json() == {"username": "ada"}
        assert r.cookies.get("ragkb_session")
        assert client.get("/auth/me").json() == {"username": "ada", "role": "user"}
        boot = client.get(
            "/bootstrap",
            params={"session_id": "00000000-0000-4000-8000-000000000002"},
        )
        assert boot.status_code == 200
        assert boot.json()["user"]["name"] == "ada"
        assert boot.json()["user"]["is_admin"] is False
        assert boot.json()["capabilities"]["reindex"] is False
        assert client.post("/index/rebuild").status_code == 403
        client.post("/auth/signout")
        assert client.get("/auth/me").status_code == 401
        assert client.get("/health").status_code == 200


def test_duplicate_username(indexed):
    with _session_client(indexed) as client:
        body = {"username": "bob", "password": "password1"}
        assert client.post("/auth/signup", json=body).status_code == 200
        client.post("/auth/signout")
        assert client.post("/auth/signup", json=body).status_code == 409


def test_bad_login_same_message(indexed):
    with _session_client(indexed) as client:
        a = client.post(
            "/auth/signin", json={"username": "nobody", "password": "password1"}
        )
        client.post("/auth/signup", json={"username": "eve", "password": "password1"})
        client.post("/auth/signout")
        b = client.post("/auth/signin", json={"username": "eve", "password": "wrongpass"})
        assert a.status_code == b.status_code == 401
        assert a.json()["detail"] == b.json()["detail"]


def test_failed_login_keeps_existing_session(indexed):
    with _session_client(indexed) as client:
        assert (
            client.post(
                "/auth/signup",
                json={"username": "ada", "password": "password1"},
            ).status_code
            == 200
        )
        unknown = client.post(
            "/auth/signin",
            json={"username": "nobody", "password": "password1"},
        )
        assert unknown.status_code == 401
        assert client.get("/auth/me").status_code == 200
        assert client.get("/auth/me").json() == {"username": "ada", "role": "user"}
        wrong = client.post(
            "/auth/signin",
            json={"username": "bob", "password": "wrongpass"},
        )
        assert wrong.status_code == 401
        assert client.get("/auth/me").json() == {"username": "ada", "role": "user"}


def test_duplicate_register_keeps_existing_session(indexed):
    with _session_client(indexed) as client:
        body = {"username": "ada", "password": "password1"}
        assert client.post("/auth/signup", json=body).status_code == 200
        assert client.post("/auth/signup", json=body).status_code == 409
        assert client.get("/auth/me").json() == {"username": "ada", "role": "user"}


def test_short_password_rejected(indexed):
    with _session_client(indexed) as client:
        r = client.post("/auth/signup", json={"username": "sam", "password": "short"})
        assert r.status_code == 422


def test_bootstrap_unauthorized_without_cookie(indexed):
    with _session_client(indexed) as client:
        r = client.get(
            "/bootstrap",
            params={"session_id": "00000000-0000-4000-8000-000000000002"},
        )
        assert r.status_code == 401


def test_session_admin_rebuild_and_bootstrap(indexed):
    with _session_client(indexed) as client:
        assert (
            client.post(
                "/auth/signup",
                json={"username": "ada", "password": "password1"},
            ).status_code
            == 200
        )
        engine = create_engine(alembic_sync_url(database_url()))
        with engine.begin() as conn:
            conn.execute(text("UPDATE users SET role = 'admin' WHERE username = 'ada'"))
        engine.dispose()
        assert client.get("/auth/me").json() == {"username": "ada", "role": "admin"}
        assert client.post("/index/rebuild").status_code == 200
        boot = client.get(
            "/bootstrap",
            params={"session_id": "00000000-0000-4000-8000-000000000003"},
        )
        assert boot.status_code == 200
        assert boot.json()["user"]["is_admin"] is True
        assert boot.json()["capabilities"]["reindex"] is True


def test_me_disabled_is_anonymous(indexed):
    indexed.auth.mode = "disabled"
    with TestClient(create_app(indexed)) as client:
        assert client.get("/auth/me").json() == {
            "username": "anonymous",
            "role": "user",
        }


def test_session_history_disabled_does_not_persist_chats(indexed):
    indexed.database_url = database_url()
    indexed.auth.mode = "session"
    indexed.history.enabled = False
    with TestClient(create_app(indexed)) as client:
        assert (
            client.post(
                "/auth/signup",
                json={"username": "ada", "password": "password1"},
            ).status_code
            == 200
        )
        created = client.post("/organization/acme/chat_conversations")
        assert created.status_code == 200
        assert created.json().get("conversation_id")
    engine = create_engine(alembic_sync_url(database_url()))
    with engine.connect() as conn:
        n = conn.execute(text("SELECT COUNT(*) FROM conversations")).scalar()
        users = conn.execute(text("SELECT COUNT(*) FROM users")).scalar()
    engine.dispose()
    assert n == 0
    assert users == 1
