from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from helpers import alembic_sync_url, database_url, migrate
from sqlalchemy import create_engine, text

from ragkb.core.config import Config, OrganizationConfig
from ragkb.core.pipeline import build_index
from ragkb.app import create_app


@pytest.fixture(scope="session", autouse=True)
def _migrate_once() -> None:
    url = os.environ.get("RAGKB_TEST_DATABASE_URL") or os.environ.get(
        "RAGKB_DATABASE_URL", ""
    )
    if not url:
        return
    migrate()


@pytest.fixture(autouse=True)
def _truncate() -> None:
    url = os.environ.get("RAGKB_TEST_DATABASE_URL") or os.environ.get(
        "RAGKB_DATABASE_URL", ""
    )
    if not url:
        return
    engine = create_engine(alembic_sync_url(url))
    with engine.begin() as conn:
        conn.execute(
            text(
                "TRUNCATE messages, conversations, sessions, users "
                "RESTART IDENTITY CASCADE"
            )
        )
        conn.execute(
            text(
                "UPDATE cleanup_state SET last_run = "
                "TIMESTAMPTZ '1970-01-01 00:00:00+00'"
            )
        )
    engine.dispose()


@pytest.fixture
def workdir(tmp_path: Path) -> Path:
    return tmp_path


@pytest.fixture
def cfg(tmp_path: Path) -> Config:
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "policy.md").write_text(
        "# Политика\n\n## Отпуск\n\nЕжегодный отпуск составляет 28 календарных дней.\n",
        encoding="utf-8",
    )
    cfg = Config(
        docs_dir=str(docs),
        index_dir=str(tmp_path / "index"),
        organization=OrganizationConfig(name="Acme", id="acme"),
    )
    cfg.store.backend = "numpy"
    cfg.database_url = database_url()
    cfg.auth.mode = "disabled"
    cfg.history.enabled = True
    cfg.logging.dir = str(tmp_path / "logs")
    return cfg


@pytest.fixture
def indexed(cfg: Config) -> Config:
    build_index(cfg)
    return cfg


@pytest.fixture
def client(indexed: Config):
    with TestClient(create_app(indexed)) as test_client:
        yield test_client
