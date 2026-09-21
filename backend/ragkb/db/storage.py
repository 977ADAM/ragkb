"""Подключение реестра корпуса; переписка и аккаунты не хранятся."""
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from ragkb.core.config import Settings
from ragkb.core.database import assert_revision, make_engine, make_session_factory
from ragkb.db.repos.corpus_documents import PostgresCorpusDocuments


class Storage:
    def __init__(self, cfg: Settings, session_factory: async_sessionmaker[AsyncSession] | None = None):
        self.engine_obj: AsyncEngine | None = None
        self._database_url = cfg.database_url
        self._sessions = session_factory
        self.corpus = PostgresCorpusDocuments(session_factory) if session_factory else None

    def ensure(self) -> None:
        if self._database_url and self._sessions is None:
            self.engine_obj = make_engine(self._database_url)
            self._sessions = make_session_factory(self.engine_obj)
            self.corpus = PostgresCorpusDocuments(self._sessions)

    async def ready(self) -> None:
        self.ensure()
        if self._sessions is not None:
            async with self._sessions() as session:
                await assert_revision(session)

    async def dispose(self) -> None:
        if self.engine_obj is not None:
            await self.engine_obj.dispose()
            self.engine_obj = None
            self._sessions = None
            self.corpus = None
