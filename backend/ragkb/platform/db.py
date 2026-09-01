"""Postgres: реэкспорт из core.database, чтобы слайсы и тесты не ломались."""
from ragkb.core.database import (
    EXPECTED_REVISION,
    Base,
    alembic_sync_url,
    assert_revision,
    make_engine,
    make_session_factory,
    needs_database,
)

__all__ = [
    "EXPECTED_REVISION",
    "Base",
    "alembic_sync_url",
    "assert_revision",
    "make_engine",
    "make_session_factory",
    "needs_database",
]
