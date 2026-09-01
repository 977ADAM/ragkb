"""Композиционный корень: собирает адаптеры слайсов."""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ragkb.core.config import Config
from ragkb.core.pipeline import RAGPipeline
from ragkb.core.ports import AnswerEngine
from ragkb.features.auth.postgres import PostgresAccounts
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
        if session_factory is None:
            ephemeral = EphemeralHistory()
            self.conversations = ephemeral
            self.answer_history = ephemeral
            self.accounts = None
        else:
            history = PostgresHistory(
                session_factory, retention_days=cfg.history.retention_days
            )
            self.conversations = history
            self.answer_history = history
            self.accounts = PostgresAccounts(session_factory)
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

    def engine(self) -> AnswerEngine:
        if self._engine is None:
            try:
                self._engine = RAGPipeline(self.cfg)
            except Exception as exc:
                raise EngineUnavailable(str(exc)) from exc
        return self._engine

    def invalidate_engine(self) -> None:
        self._engine = None
