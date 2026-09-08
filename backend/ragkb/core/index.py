"""Индекс корпуса: пересборка и манифест без знания HTTP."""
from __future__ import annotations

import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

from ragkb.core import loaders
from ragkb.core.config import Settings
from ragkb.core.errors import EngineUnavailable, InvalidRequest
from ragkb.core.pipeline import build_index, remove_document
from ragkb.core.ports import AnswerEngine
from ragkb.core.store import MANIFEST


class ConfigIndex:
    def __init__(self, cfg: Settings, get_engine: Callable[[], AnswerEngine]):
        self.cfg = cfg
        self._engine = get_engine

    def stats(self) -> dict[str, Any]:
        return self._engine().stats()

    def rebuild(self):
        return build_index(self.cfg)

    def manifest(self) -> dict[str, Any]:
        engine = self._engine()
        store = getattr(engine, "store", None)
        if store is None:
            raise EngineUnavailable("Индекс недоступен")
        return store.manifest

    def reindex_after_delete(self, path: str) -> None:
        manifest_path = Path(self.cfg.index_dir) / MANIFEST
        if not manifest_path.exists():
            return
        if not loaders.discover(Path(self.cfg.docs_dir)):
            shutil.rmtree(Path(self.cfg.index_dir), ignore_errors=True)
            return
        if self.cfg.store.backend.lower() == "chroma":
            remove_document(self.cfg, path)
            return
        try:
            build_index(self.cfg)
        except ValueError as exc:
            raise InvalidRequest(f"Не удалось пересобрать индекс: {exc}") from exc
