"""Реестр путей документов в индексе."""
from __future__ import annotations

from ragkb.core.errors import EngineUnavailable
from ragkb.core.ports import IndexEngine


class IndexSources:
    """Пути документов, лежащих в индексе.

    Манифест берём у индекса, а не у движка: движок поднимает модель
    эмбеддингов, а для отметки исчезнувших источников нужен только список
    файлов.
    """

    def __init__(self, index: IndexEngine):
        self._index = index

    def document_paths(self) -> set[str] | None:
        try:
            manifest = self._index.manifest()
        except EngineUnavailable:
            return None
        return {d.get("source", "") for d in manifest.get("documents", [])}
