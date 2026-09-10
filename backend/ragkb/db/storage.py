"""Учётки, история и оценки: Postgres или память."""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from ragkb.core.config import Settings
from ragkb.core.database import make_engine, make_session_factory, needs_database
from ragkb.db.repos.auth import PostgresAccounts
from ragkb.db.repos.corpus_documents import PostgresCorpusDocuments
from ragkb.db.repos.ephemeral_history import EphemeralHistory
from ragkb.db.repos.feedback import PostgresFeedback
from ragkb.db.repos.postgres_history import PostgresHistory


class Storage:
    def __init__(
        self,
        cfg: Settings,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
    ):
        self.cfg = cfg
        self.engine_obj: AsyncEngine | None = None
        self._database_url = ""
        self.conversations: EphemeralHistory | PostgresHistory | None = None
        self.answer_history: EphemeralHistory | PostgresHistory | None = None
        self.accounts: PostgresAccounts | None = None
        self.feedback: PostgresFeedback | None = None
        # Реестр документов корпуса: без него индекс собирается из всего
        # каталога, как было до появления загрузки через интерфейс.
        self.corpus: PostgresCorpusDocuments | None = None
        self._bind(session_factory)

    def _bind(
        self,
        session_factory: async_sessionmaker[AsyncSession] | None,
    ) -> None:
        if session_factory is not None:
            self._bind_postgres(session_factory)
            return
        if needs_database(self.cfg):
            if not self.cfg.database_url:
                raise RuntimeError("Задайте RAGKB_DATABASE_URL")
            self._database_url = self.cfg.database_url
            return
        ephemeral = EphemeralHistory()
        self.conversations = ephemeral
        self.answer_history = ephemeral

    def _bind_postgres(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        if self.cfg.history.enabled:
            history = PostgresHistory(
                session_factory, retention_days=self.cfg.history.retention_days
            )
            self.conversations = history
            self.answer_history = history
        else:
            ephemeral = EphemeralHistory()
            self.conversations = ephemeral
            self.answer_history = ephemeral
        self.accounts = PostgresAccounts(session_factory)
        self.feedback = PostgresFeedback(session_factory)
        self.corpus = PostgresCorpusDocuments(session_factory)

    def ensure(self) -> None:
        if self._database_url and self.engine_obj is None:
            self.engine_obj = make_engine(self._database_url)
            self._bind_postgres(make_session_factory(self.engine_obj))

    async def ready(self) -> None:
        self.ensure()
        if isinstance(self.conversations, PostgresHistory):
            await self.conversations.ready()
        if self.accounts is not None:
            await self.accounts.ready()

    async def dispose(self) -> None:
        if self.engine_obj is not None:
            await self.engine_obj.dispose()
            self.engine_obj = None
