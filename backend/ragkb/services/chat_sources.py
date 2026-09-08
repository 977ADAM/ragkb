"""Реестр путей документов в индексе."""
from __future__ import annotations

from collections.abc import Callable

from ragkb.core.errors import EngineUnavailable
from ragkb.core.ports import AnswerEngine


class IndexSources:
    def __init__(self, get_engine: Callable[[], AnswerEngine]):
        self._get_engine = get_engine

    def document_paths(self) -> set[str] | None:
        try:
            return self._get_engine().document_paths()
        except EngineUnavailable:
            return None
