from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ragkb.core.config import Config
from ragkb.core.errors import EngineUnavailable
from ragkb.core.pipeline import build_index
from ragkb.core.ports import AnswerEngine


class IndexService:
    def __init__(
        self,
        cfg: Config,
        get_engine: Callable[[], AnswerEngine],
        invalidate: Callable[[], None],
    ):
        self.cfg = cfg
        self._engine = get_engine
        self._invalidate = invalidate

    def status(self) -> dict[str, Any]:
        try:
            return {"status": "ok", **self._engine().stats()}
        except EngineUnavailable as exc:
            return {"status": "no_index", "detail": exc.detail}

    def rebuild(self) -> dict[str, Any]:
        report = build_index(self.cfg)
        self._invalidate()
        return {
            "files": report.files,
            "chunks": report.chunks,
            "skipped": report.skipped,
            "elapsed_sec": round(report.elapsed, 1),
        }
