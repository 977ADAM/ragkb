from pathlib import Path

import pytest

from ragkb.core.config import Config
from ragkb.platform.app import create_app


def test_history_enabled_env_false_zero_no(monkeypatch: pytest.MonkeyPatch) -> None:
    for raw in ("false", "0", "no", "FALSE"):
        cfg = Config()
        cfg.history.enabled = True
        monkeypatch.setenv("RAGKB_HISTORY_ENABLED", raw)
        cfg._apply_env()
        assert cfg.history.enabled is False, raw


def test_history_enabled_env_true_when_set(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = Config()
    cfg.history.enabled = False
    monkeypatch.setenv("RAGKB_HISTORY_ENABLED", "true")
    cfg._apply_env()
    assert cfg.history.enabled is True


def test_create_app_requires_database_url_when_history_enabled() -> None:
    cfg = Config()
    cfg.auth.mode = "disabled"
    cfg.database_url = ""
    cfg.store.backend = "numpy"
    with pytest.raises(RuntimeError, match="Задайте RAGKB_DATABASE_URL"):
        create_app(cfg)


def test_create_app_does_not_touch_repo_history(tmp_path: Path) -> None:
    """disabled + история выкл. не требует URL и не пишет sqlite."""
    cfg = Config()
    cfg.auth.mode = "disabled"
    cfg.history.enabled = False
    cfg.database_url = ""
    cfg.store.backend = "numpy"
    cfg.index_dir = str(tmp_path / "idx")
    create_app(cfg)
    backend_default = Path(__file__).resolve().parents[1].parent / "data" / "history.sqlite3"
    assert not (tmp_path / "h.sqlite3").exists()
    _ = backend_default


def test_me_disabled_without_database(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    cfg = Config()
    cfg.auth.mode = "disabled"
    cfg.history.enabled = False
    cfg.database_url = ""
    cfg.store.backend = "numpy"
    cfg.index_dir = str(tmp_path / "idx")
    with TestClient(create_app(cfg)) as client:
        assert client.get("/auth/me").json() == {"username": "anonymous"}
        assert client.get("/health").status_code == 200


def test_alembic_sync_url_sqlite_and_postgres() -> None:
    from ragkb.core.database import alembic_sync_url

    assert alembic_sync_url("sqlite+aiosqlite:////tmp/x.db") == "sqlite:////tmp/x.db"
    assert (
        alembic_sync_url("postgresql+asyncpg://u:p@h/db")
        == "postgresql+psycopg://u:p@h/db"
    )


def test_session_auth_on_sqlite(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from fastapi.testclient import TestClient
    from helpers import migrate

    db = tmp_path / "ragkb.sqlite3"
    url = f"sqlite+aiosqlite:///{db}"
    monkeypatch.setenv("RAGKB_DATABASE_URL", url)
    migrate()
    cfg = Config()
    cfg.database_url = url
    cfg.auth.mode = "session"
    cfg.history.enabled = True
    cfg.store.backend = "numpy"
    cfg.index_dir = str(tmp_path / "idx")
    with TestClient(create_app(cfg)) as client:
        r = client.post(
            "/auth/signup", json={"username": "ada", "password": "password1"}
        )
        assert r.status_code == 200
        assert r.json() == {"username": "ada"}
        assert client.get("/auth/me").json() == {"username": "ada"}
