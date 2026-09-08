from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ragkb.core.errors import EngineUnavailable
from ragkb.core.ports import IndexEngine


class IndexService:
    def __init__(self, index: IndexEngine, invalidate: Callable[[], None]):
        self._index = index
        self._invalidate = invalidate

    def status(self) -> dict[str, Any]:
        try:
            return {"status": "ok", **self._index.stats()}
        except EngineUnavailable as exc:
            return {"status": "no_index", "detail": exc.detail}

    def rebuild(self) -> dict[str, Any]:
        report = self._index.rebuild()
        self._invalidate()
        return {
            "files": report.files,
            "chunks": report.chunks,
            "skipped": report.skipped,
            "elapsed_sec": round(report.elapsed, 1),
        }
