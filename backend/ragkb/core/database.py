"""Подключение к Postgres + DeclarativeBase. Схему накатывает Alembic."""
from __future__ import annotations

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from ragkb.core.config import Config

EXPECTED_REVISION = "0007_message_feedback"


class Base(DeclarativeBase):
    pass


def needs_database(cfg: Config) -> bool:
    return cfg.history.enabled or cfg.auth.mode == "session"


def alembic_sync_url(url: str) -> str:
    if url.startswith("sqlite+aiosqlite:"):
        return "sqlite:" + url.removeprefix("sqlite+aiosqlite:")
    return url.replace("+asyncpg", "+psycopg", 1)


def make_engine(url: str) -> AsyncEngine:
    if url.startswith("sqlite"):
        engine = create_async_engine(url)
        @event.listens_for(engine.sync_engine, "connect")
        def _sqlite_fk(dbapi_connection, _connection_record) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

        return engine
    return create_async_engine(url, pool_pre_ping=True)


def make_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


async def assert_revision(session: AsyncSession) -> None:
    try:
        result = await session.execute(text("SELECT version_num FROM alembic_version"))
        found = [row[0] for row in result.all()]
    except Exception as exc:
        raise RuntimeError(
            f"Код ждёт ревизию {EXPECTED_REVISION}. "
            "Выполните: alembic upgrade head"
        ) from exc
    if len(found) != 1 or found[0] != EXPECTED_REVISION:
        raise RuntimeError(
            f"Ревизия базы: {found!r}, "
            f"код ждёт {EXPECTED_REVISION}. "
            "Выполните alembic upgrade head или откатитесь на нужный образ."
        )
