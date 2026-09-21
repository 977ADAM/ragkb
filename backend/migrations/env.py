"""Alembic: схема Postgres. Приложение схему не накатывает."""
from __future__ import annotations

import logging
import os
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import create_engine, event, pool

_BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from ragkb.core.config import Settings
from ragkb.core.database import Base, alembic_sync_url
from ragkb.db.models import CorpusDocumentRow

config = context.config
target_metadata = Base.metadata

assert CorpusDocumentRow.metadata is target_metadata
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Явный логгер для alembic-миграций
logger = logging.getLogger("alembic.runtime.migration")


def _async_url() -> str:
    x_args = context.get_x_argument(as_dictionary=True)
    if x_args.get("url"):
        return x_args["url"]
    env = os.environ.get("RAGKB_DATABASE_URL")
    if env:
        return env
    url = Settings().database_url
    if not url:
        logger.error("Не задан RAGKB_DATABASE_URL")
        sys.exit(1)
    return url


def _sync_url(url: str) -> str:
    if not url:
        logger.error("Не задан RAGKB_DATABASE_URL")
        sys.exit(1)
    logger.info("Подключение к БД: %s", url.rsplit("@", 1)[-1])
    return alembic_sync_url(url)


def run_migrations_offline() -> None:
    logger.error("Попытка запустить офлайн-миграции, которые отключены")
    raise RuntimeError("Офлайн-миграции не используются")


def run_migrations_online() -> None:
    try:
        url = _sync_url(_async_url())
    except Exception:
        logger.exception("Не удалось определить URL для миграций")
        raise

    engine = create_engine(url, poolclass=pool.NullPool)
    if url.startswith("sqlite"):

        @event.listens_for(engine, "connect")
        def _sqlite_fk(dbapi_connection, _connection_record) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    logger.info("Запуск миграций")
    with engine.connect() as conn:
        context.configure(connection=conn, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()
    logger.info("Миграции завершены")


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()