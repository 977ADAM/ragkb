from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from helpers import make_app
from sqlalchemy import create_engine, text

from ragkb.core.config import Settings
from ragkb.core.pipeline import build_index


@pytest.fixture
def workdir(tmp_path: Path) -> Path:
    return tmp_path


@pytest.fixture
def cfg(tmp_path: Path) -> Settings:
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "policy.md").write_text(
        "# Политика\n\n## Отпуск\n\nЕжегодный отпуск составляет 28 календарных дней.\n",
        encoding="utf-8",
    )
    cfg = Settings(
        docs_dir=str(docs),
        index_dir=str(tmp_path / "index"),
        organization=Settings.OrganizationConfig(name="Acme", id="acme"),
    )
    cfg.store.backend = "numpy"
    cfg.database_url = ""
    cfg.logging.dir = str(tmp_path / "logs")
    return cfg


@pytest.fixture
def indexed(cfg: Settings) -> Settings:
    build_index(cfg)
    return cfg


@pytest.fixture
def client(indexed: Settings):
    with TestClient(make_app(indexed)) as test_client:
        yield test_client


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch):
    """Never connect tests to credentials from a developer's .env."""
    for key in tuple(os.environ):
        if key.startswith('RAGKB_') or key.startswith('POSTGRES_'):
            monkeypatch.delenv(key, raising=False)
    for key in ('POSTGRES_USER', 'POSTGRES_PASSWORD', 'POSTGRES_DB'):
        monkeypatch.setenv(key, '')
