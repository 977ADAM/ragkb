from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from helpers import alembic_sync_url, database_url, migrate
from sqlalchemy import create_engine, text

from ragkb.features.auth.passwords import hash_password, verify_password
from ragkb.features.auth.sqlite import SqliteAccounts
from ragkb.platform.app import create_app


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
        assert rev == "0001_postgres_history_auth"
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


def _session_client(cfg):
    cfg.auth.mode = "session"
    return TestClient(create_app(cfg))


def test_register_login_me_logout_bootstrap(indexed):
    client = _session_client(indexed)
    r = client.post(
        "/auth/register",
        json={"username": "Ada", "password": "password1"},
    )
    assert r.status_code == 200
    assert r.json() == {"username": "ada"}
    assert r.cookies.get("ragkb_session")
    assert client.get("/auth/me").json() == {"username": "ada"}
    boot = client.get(
        "/bootstrap",
        params={"session_id": "00000000-0000-4000-8000-000000000002"},
    )
    assert boot.status_code == 200
    assert boot.json()["user"]["name"] == "ada"
    client.post("/auth/logout")
    assert client.get("/auth/me").status_code == 401
    assert client.get("/health").status_code == 200


def test_duplicate_username(indexed):
    client = _session_client(indexed)
    body = {"username": "bob", "password": "password1"}
    assert client.post("/auth/register", json=body).status_code == 200
    client.post("/auth/logout")
    assert client.post("/auth/register", json=body).status_code == 409


def test_bad_login_same_message(indexed):
    client = _session_client(indexed)
    a = client.post("/auth/login", json={"username": "nobody", "password": "password1"})
    client.post("/auth/register", json={"username": "eve", "password": "password1"})
    client.post("/auth/logout")
    b = client.post("/auth/login", json={"username": "eve", "password": "wrongpass"})
    assert a.status_code == b.status_code == 401
    assert a.json()["detail"] == b.json()["detail"]


def test_failed_login_keeps_existing_session(indexed):
    client = _session_client(indexed)
    assert (
        client.post(
            "/auth/register",
            json={"username": "ada", "password": "password1"},
        ).status_code
        == 200
    )
    unknown = client.post(
        "/auth/login",
        json={"username": "nobody", "password": "password1"},
    )
    assert unknown.status_code == 401
    assert client.get("/auth/me").status_code == 200
    assert client.get("/auth/me").json() == {"username": "ada"}
    wrong = client.post(
        "/auth/login",
        json={"username": "bob", "password": "wrongpass"},
    )
    assert wrong.status_code == 401
    assert client.get("/auth/me").json() == {"username": "ada"}


def test_duplicate_register_keeps_existing_session(indexed):
    client = _session_client(indexed)
    body = {"username": "ada", "password": "password1"}
    assert client.post("/auth/register", json=body).status_code == 200
    assert client.post("/auth/register", json=body).status_code == 409
    assert client.get("/auth/me").json() == {"username": "ada"}


def test_short_password_rejected(indexed):
    client = _session_client(indexed)
    r = client.post("/auth/register", json={"username": "sam", "password": "short"})
    assert r.status_code == 422


def test_bootstrap_unauthorized_without_cookie(indexed):
    client = _session_client(indexed)
    r = client.get(
        "/bootstrap",
        params={"session_id": "00000000-0000-4000-8000-000000000002"},
    )
    assert r.status_code == 401


def test_me_disabled_is_anonymous(indexed):
    indexed.auth.mode = "disabled"
    client = TestClient(create_app(indexed))
    assert client.get("/auth/me").json() == {"username": "anonymous"}
