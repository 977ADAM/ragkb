"""Подключение к БД + Base + Unit-of-Work зависимость (зеркало монолита/auth)."""

from collections.abc import AsyncGenerator
from typing import Any

from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.core.config import get_settings


class Base(DeclarativeBase):
    pass


_settings = get_settings()
_engine_kwargs: dict[str, Any] = {"echo": False}
# Диалект берём у разобранного URL, а не подстрокой по всему DSN: «sqlite» может
# оказаться в имени БД или в пароле.
if make_url(_settings.db_url).get_backend_name() != "sqlite":
    _engine_kwargs["pool_size"] = 5
    # Этот engine живёт весь процесс FastAPI, а MariaDB рвёт простаивающие
    # соединения по wait_timeout (8 ч). Трафик у сервиса редкий, healthcheck'и
    # в compose сняты (LXC) — без пинга первый утренний запрос получал бы
    # «server has gone away». Цена — лёгкий SELECT 1 при выдаче соединения.
    # Движкам UoW/visits/sync это не нужно: они создаются под вызов.
    _engine_kwargs["pool_pre_ping"] = True
    _engine_kwargs["pool_recycle"] = 1800

engine = create_async_engine(_settings.db_url, **_engine_kwargs)
SessionFactory = async_sessionmaker(engine, expire_on_commit=False)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Сессия на запрос: commit на успех, rollback на любую ошибку."""
    async with SessionFactory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
