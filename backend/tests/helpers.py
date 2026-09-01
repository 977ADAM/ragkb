from __future__ import annotations

import os
from pathlib import Path

from alembic import command
from alembic.config import Config as AlembicConfig

BACKEND_ROOT = Path(__file__).resolve().parents[1]


def database_url() -> str:
    url = os.environ.get("RAGKB_TEST_DATABASE_URL") or os.environ.get(
        "RAGKB_DATABASE_URL", ""
    )
    if not url:
        raise RuntimeError(
            "Для тестов нужен Postgres: задайте RAGKB_TEST_DATABASE_URL "
            "или RAGKB_DATABASE_URL (postgresql+asyncpg://…)."
        )
    return url


def alembic_sync_url(url: str) -> str:
    return url.replace("+asyncpg", "+psycopg", 1)


def migrate() -> None:
    os.environ["RAGKB_DATABASE_URL"] = database_url()
    cfg = AlembicConfig(str(BACKEND_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_ROOT / "migrations"))
    command.upgrade(cfg, "head")
