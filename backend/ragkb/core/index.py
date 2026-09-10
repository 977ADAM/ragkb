"""Индекс корпуса: пересборка и манифест без знания HTTP."""
from __future__ import annotations

import json
import shutil
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from ragkb.core import loaders
from ragkb.core.config import Settings
from ragkb.core.errors import Conflict, EngineUnavailable, InvalidRequest
from ragkb.core.llm import build_llm
from ragkb.core.pipeline import build_index, remove_document
from ragkb.core.ports import AnswerEngine
from ragkb.core.store import MANIFEST


class ConfigIndex:
    """Индекс корпуса: сборка и сведения о нём.

    Манифест и статус читаются с диска, без сборки движка: движок поднимает
    модель эмбеддингов (гигабайты памяти и десятки секунд на CPU), а списку
    документов, статусу и проверке живости она не нужна.
    """

    def __init__(self, cfg: Settings, get_engine: Callable[[], AnswerEngine]):
        self.cfg = cfg
        self._engine = get_engine
        self._rebuild_lock = threading.Lock()

    def stats(self) -> dict[str, Any]:
        manifest = self.manifest()
        llm = build_llm(self.cfg.llm)
        return {
            "chunks": int(manifest.get("n_chunks", 0)),
            "documents": len(manifest.get("documents", [])),
            "store": manifest.get("backend"),
            "embedder": manifest.get("embedder"),
            "llm": llm.name,
            "llm_available": llm.available(),
            "index_dir": str(self.cfg.index_dir),
        }

    def probe(self) -> str:
        """«Собран ли индекс» — дешёвая проверка для /health."""
        try:
            self.manifest()
        except EngineUnavailable:
            return "no_index"
        return "ok"

    def manifest(self) -> dict[str, Any]:
        path = Path(self.cfg.index_dir) / MANIFEST
        if not path.exists():
            raise EngineUnavailable(f"Индекс не найден в {self.cfg.index_dir}")
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except ValueError as exc:
            raise EngineUnavailable(f"Манифест индекса повреждён: {exc}") from exc

    def rebuild(self, allow: frozenset[str] | None = None):
        """Полная переиндексация документов, принятых в корпус.

        `allow` — имена из реестра документов; None значит «индексировать
        всё, что нашлось в каталоге» (режим без реестра).

        Сборка идёт по одной за раз: параллельные пересборки не ускоряются
        (ядра общие), а память и кеш эмбеддера делят между собой.
        """
        if not self._rebuild_lock.acquire(blocking=False):
            raise Conflict("Индексация уже идёт — дождитесь её завершения")
        try:
            return build_index(self.cfg, allow=_by_registry(allow))
        finally:
            self._rebuild_lock.release()

    def reindex_after_delete(self, path: str, allow: frozenset[str] | None = None) -> None:
        manifest_path = Path(self.cfg.index_dir) / MANIFEST
        if not manifest_path.exists():
            return
        root = Path(self.cfg.docs_dir)
        predicate = _by_registry(allow)
        # «Корпус опустел» считаем по принятым документам, а не по каталогу:
        # файлы мимо интерфейса в индексе не участвуют, и оставшийся из них
        # каталог не повод держать индекс, которого больше не на чем собрать.
        remaining = [
            candidate
            for candidate in loaders.discover(root)
            if predicate is None or predicate(loaders.relative_name(candidate, root))
        ]
        if not remaining:
            shutil.rmtree(Path(self.cfg.index_dir), ignore_errors=True)
            return
        if self.cfg.store.backend.lower() == "chroma":
            remove_document(self.cfg, path)
            return
        try:
            build_index(self.cfg, allow=predicate)
        except ValueError as exc:
            raise InvalidRequest(f"Не удалось пересобрать индекс: {exc}") from exc


def _by_registry(allow: frozenset[str] | None):
    """Предикат «документ принят в корпус» для ядра индексации."""
    if allow is None:
        return None
    return lambda name: name in allow
