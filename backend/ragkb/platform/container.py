"""Композиционный корень: собирает адаптеры слайсов."""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from ragkb.core.config import Config
from ragkb.core.database import make_engine, make_session_factory, needs_database
from ragkb.core.pipeline import RAGPipeline
from ragkb.core.ports import AnswerEngine
from ragkb.db.repos.auth import PostgresAccounts
from ragkb.features.chat_conversations.ephemeral import EphemeralHistory
from ragkb.features.chat_conversations.postgres import PostgresHistory
from ragkb.features.models.ollama import OllamaCatalog
from ragkb.features.models.openai import OpenAICatalog
from ragkb.features.models.static import StaticCatalog
from ragkb.features.telemetry.stdout import StdoutSink
from ragkb.platform.errors import EngineUnavailable


class Container:
    def __init__(
        self,
        cfg: Config,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
    ):
        self.cfg = cfg
        self._engine: AnswerEngine | None = None
        self.engine_obj: AsyncEngine | None = None
        self._database_url = ""
        self.conversations: EphemeralHistory | PostgresHistory | None = None
        self.answer_history: EphemeralHistory | PostgresHistory | None = None
        self.accounts: PostgresAccounts | None = None
        if session_factory is None and needs_database(cfg):
            
            # Engine — в ready() / первом запросе, на цикле TestClient.
            self._database_url = cfg.database_url
        elif session_factory is None:
            ephemeral = EphemeralHistory()
            self.conversations = ephemeral
            self.answer_history = ephemeral
        else:
            self._bind_postgres(session_factory)
        kind = cfg.llm.backend.lower()
        if kind in {"openai", "vllm", "openai-compatible"}:
            self.models = OpenAICatalog(cfg.llm)
        elif kind == "ollama":
            self.models = OllamaCatalog(cfg.llm)
        else:
            self.models = StaticCatalog(cfg.llm)
        self.events = StdoutSink()
        self.history_window = cfg.history.window
        self.history_enabled = cfg.history.enabled

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

    def _ensure_postgres(self) -> None:
        if self._database_url and self.engine_obj is None:
            self.engine_obj = make_engine(self._database_url)
            self._bind_postgres(make_session_factory(self.engine_obj))

    async def ready(self) -> None:
        self._ensure_postgres()
        if isinstance(self.conversations, PostgresHistory):
            await self.conversations.ready()
        if self.accounts is not None:
            await self.accounts.ready()

    async def dispose(self) -> None:
        if self.engine_obj is not None:
            await self.engine_obj.dispose()
            self.engine_obj = None

    def engine(self) -> AnswerEngine:
        if self._engine is None:
            try:
                self._engine = RAGPipeline(self.cfg)
            except Exception as exc:
                raise EngineUnavailable(str(exc)) from exc
        return self._engine

    def invalidate_engine(self) -> None:
        self._engine = None
