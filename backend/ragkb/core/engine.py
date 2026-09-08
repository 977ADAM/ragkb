"""Ленивый RAGPipeline: один на процесс, сброс после переиндексации."""
from __future__ import annotations

from ragkb.core.config import Settings
from ragkb.core.errors import EngineUnavailable
from ragkb.core.pipeline import RAGPipeline
from ragkb.core.ports import AnswerEngine


class EngineCache:
    def __init__(self, cfg: Settings):
        self.cfg = cfg
        self._engine: AnswerEngine | None = None

    def __call__(self) -> AnswerEngine:
        if self._engine is None:
            try:
                self._engine = RAGPipeline(self.cfg)
            except Exception as exc:
                raise EngineUnavailable(str(exc)) from exc
        return self._engine

    def invalidate(self) -> None:
        self._engine = None
