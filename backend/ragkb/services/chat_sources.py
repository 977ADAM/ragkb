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
            stats = self._get_engine().stats()
        except EngineUnavailable:
            return None
        # stats() не несёт список путей — берём через pipeline.store, если есть.
        engine = self._get_engine()
        store = getattr(engine, "store", None)
        if store is None:
            return None
        documents = store.manifest.get("documents", [])
        return {d.get("source", "") for d in documents}
