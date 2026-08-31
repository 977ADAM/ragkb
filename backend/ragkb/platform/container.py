"""Композиционный корень: собирает адаптеры слайсов."""
from __future__ import annotations

from ragkb.core.config import Config
from ragkb.core.pipeline import RAGPipeline
from ragkb.core.ports import AnswerEngine
from ragkb.features.chat_conversations.ephemeral import EphemeralHistory
from ragkb.features.chat_conversations.sqlite import SqliteHistory
from ragkb.features.models.ollama import OllamaCatalog
from ragkb.features.models.static import StaticCatalog
from ragkb.features.telemetry.stdout import StdoutSink
from ragkb.platform.errors import EngineUnavailable


class Container:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self._engine: AnswerEngine | None = None
        if cfg.history.enabled:
            store = SqliteHistory(cfg.history.path, retention_days=cfg.history.retention_days)
            self.conversations = store
            self.answer_history = store
        else:
            ephemeral = EphemeralHistory()
            self.conversations = ephemeral
            self.answer_history = ephemeral
        if cfg.llm.backend.lower() == "ollama":
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
