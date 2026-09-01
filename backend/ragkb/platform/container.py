"""Композиционный корень: собирает адаптеры слайсов."""
from __future__ import annotations

from ragkb.core.config import Config
from ragkb.core.pipeline import RAGPipeline
from ragkb.core.ports import AnswerEngine
from ragkb.features.auth.sqlite import SqliteAccounts
from ragkb.features.chat_conversations.ephemeral import EphemeralHistory
from ragkb.features.models.ollama import OllamaCatalog
from ragkb.features.models.openai import OpenAICatalog
from ragkb.features.models.static import StaticCatalog
from ragkb.features.telemetry.stdout import StdoutSink
from ragkb.platform.errors import EngineUnavailable


class Container:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.accounts = SqliteAccounts(cfg.history.path)
        self._engine: AnswerEngine | None = None
        # Task 6 wires PostgresHistory via session factory; EphemeralHistory until then.
        ephemeral = EphemeralHistory()
        self.conversations = ephemeral
        self.answer_history = ephemeral
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
