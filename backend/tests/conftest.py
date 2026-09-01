from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from helpers import migrate
from ragkb.core.config import Config, OrganizationConfig
from ragkb.core.pipeline import build_index
from ragkb.platform.app import create_app


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
    history = tmp_path / "history.sqlite3"
    migrate(history)
    cfg = Config(
        docs_dir=str(docs),
        index_dir=str(tmp_path / "index"),
        organization=OrganizationConfig(name="Acme", id="acme"),
    )
    cfg.store.backend = "numpy"
    cfg.history.path = str(history)
    cfg.auth.mode = "disabled"
    cfg.logging.dir = str(tmp_path / "logs")
    return cfg


@pytest.fixture
def indexed(cfg: Config) -> Config:
    build_index(cfg)
    return cfg


@pytest.fixture
def client(indexed: Config) -> TestClient:
    return TestClient(create_app(indexed))
