from pathlib import Path

import pytest
from helpers import BACKEND_ROOT, make_app

from ragkb.core.config import Settings
from ragkb.db.storage import Storage


def test_history_enabled_env_false_zero_no(monkeypatch: pytest.MonkeyPatch) -> None:
    for raw in ("false", "0", "no", "FALSE"):
        cfg = Settings()
        cfg.history.enabled = True
        monkeypatch.setenv("RAGKB_HISTORY_ENABLED", raw)
        cfg._apply_env()
        assert cfg.history.enabled is False, raw


def test_history_enabled_env_true_when_set(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = Settings()
    cfg.history.enabled = False
    monkeypatch.setenv("RAGKB_HISTORY_ENABLED", "true")
    cfg._apply_env()
    assert cfg.history.enabled is True


def test_storage_requires_database_url_when_history_enabled() -> None:
    cfg = Settings()
    cfg.auth.mode = "disabled"
    cfg.database_url = ""
    cfg.store.backend = "numpy"
    with pytest.raises(RuntimeError, match="Задайте RAGKB_DATABASE_URL"):
        Storage(cfg)


def test_storage_does_not_touch_repo_history(tmp_path: Path) -> None:
    """disabled + история выкл. не требует URL и не пишет sqlite."""
    cfg = Settings()
    cfg.auth.mode = "disabled"
    cfg.history.enabled = False
    cfg.database_url = ""
    cfg.store.backend = "numpy"
    cfg.index_dir = str(tmp_path / "idx")
    Storage(cfg)
    backend_default = Path(__file__).resolve().parents[1].parent / "data" / "history.sqlite3"
    assert not (tmp_path / "h.sqlite3").exists()
    _ = backend_default


def test_me_disabled_without_database(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    cfg = Settings()
    cfg.auth.mode = "disabled"
    cfg.history.enabled = False
    cfg.database_url = ""
    cfg.store.backend = "numpy"
    cfg.index_dir = str(tmp_path / "idx")
    with TestClient(make_app(cfg)) as client:
        assert client.get("/auths/me").status_code == 404
        assert client.get("/api/v1/auths/me").json() == {
            "username": "anonymous",
            "role": "admin",
        }
        assert client.get("/health").status_code == 200


def test_alembic_sync_url_sqlite_and_postgres() -> None:
    from ragkb.core.database import alembic_sync_url

    assert alembic_sync_url("sqlite+aiosqlite:////tmp/x.db") == "sqlite:////tmp/x.db"
    assert (
        alembic_sync_url("postgresql+asyncpg://u:p@h/db")
        == "postgresql+psycopg://u:p@h/db"
    )


def test_signup_is_closed_on_sqlite(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from alembic import command
    from alembic.config import Config as AlembicConfig
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine, text

    from ragkb.core.database import alembic_sync_url

    db = tmp_path / "ragkb.sqlite3"
    url = f"sqlite+aiosqlite:///{db}"
    cfg_alembic = AlembicConfig(str(BACKEND_ROOT / "alembic.ini"))
    cfg_alembic.set_main_option("script_location", str(BACKEND_ROOT / "migrations"))
    monkeypatch.setenv("RAGKB_DATABASE_URL", url)
    command.upgrade(cfg_alembic, "head")
    cfg = Settings()
    cfg.database_url = url
    cfg.auth.mode = "session"
    cfg.history.enabled = True
    cfg.store.backend = "numpy"
    cfg.index_dir = str(tmp_path / "idx")
    with TestClient(make_app(cfg)) as client:
        r = client.post(
            "/api/v1/auths/signup", json={"username": "ada", "password": "password1"}
        )
        assert r.status_code == 403
        assert r.json()["detail"] == "регистрация закрыта, учётку создаёт администратор"
        assert r.cookies.get("ragkb_session") is None
        assert client.get("/api/v1/auths/me").status_code == 401
    engine = create_engine(alembic_sync_url(url))
    with engine.connect() as conn:
        n = conn.execute(text("SELECT COUNT(*) FROM users")).scalar()
    engine.dispose()
    assert n == 0


def test_session_auth_on_sqlite(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import asyncio

    from alembic import command
    from alembic.config import Config as AlembicConfig
    from fastapi.testclient import TestClient

    from ragkb.core.database import make_engine, make_session_factory
    from ragkb.db.repos.auth import PostgresAccounts
    from ragkb.services.auth import hash_password

    db = tmp_path / "ragkb.sqlite3"
    url = f"sqlite+aiosqlite:///{db}"
    cfg_alembic = AlembicConfig(str(BACKEND_ROOT / "alembic.ini"))
    cfg_alembic.set_main_option("script_location", str(BACKEND_ROOT / "migrations"))
    monkeypatch.setenv("RAGKB_DATABASE_URL", url)
    command.upgrade(cfg_alembic, "head")

    async def _seed() -> None:
        engine = make_engine(url)
        store = PostgresAccounts(make_session_factory(engine))
        await store.create_user("ada", hash_password("password1"), role="user")
        await engine.dispose()

    asyncio.run(_seed())
    cfg = Settings()
    cfg.database_url = url
    cfg.auth.mode = "session"
    cfg.history.enabled = True
    cfg.store.backend = "numpy"
    cfg.index_dir = str(tmp_path / "idx")
    with TestClient(make_app(cfg)) as client:
        r = client.post(
            "/api/v1/auths/signin",
            json={"username": "ada", "password": "password1"},
        )
        assert r.status_code == 200
        assert client.get("/api/v1/auths/me").json() == {
            "username": "ada",
            "role": "user",
        }
