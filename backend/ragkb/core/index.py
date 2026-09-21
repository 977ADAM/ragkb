"""Индекс корпуса: пересборка и сведения о нём без знания HTTP.

Манифест и статус читаются с диска, без сборки движка: движок поднимает
эмбеддер и хранилище (запросы к Ollama, открытие коллекции), а списку
документов, статусу и проверке живости это не нужно.
"""
from __future__ import annotations

import shutil
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from ragkb.core import loaders, manifest
from ragkb.core.config import Settings
from ragkb.core.errors import Conflict, InvalidRequest
from ragkb.core.llm import chat_model_name
from ragkb.core.pipeline import build_index, remove_document
from ragkb.core.ports import AnswerEngine


class ConfigIndex:
    """Индекс корпуса: сборка и сведения о нём."""

    def __init__(self, cfg: Settings, get_engine: Callable[[], AnswerEngine]):
        self.cfg = cfg
        self._engine = get_engine
        self._rebuild_lock = threading.Lock()

    def stats(self) -> dict[str, Any]:
        indexed = self.manifest()
        return {
            "chunks": int(indexed.get("n_chunks", 0)),
            "documents": len(indexed.get("documents", [])),
            "store": indexed.get("store"),
            "embedder": indexed.get("embedder"),
            "llm": chat_model_name(self.cfg.llm),
            # Проверка по конфигурации: живой список моделей отдаёт bootstrap,
            # а статус не должен ходить в сеть.
            "llm_available": bool(self.cfg.llm.base_url and self.cfg.llm.model),
            "index_dir": str(Path(self.cfg.index_dir).expanduser().resolve()),
        }

    def probe(self) -> str:
        """«Собран ли индекс» — дешёвая проверка для /health."""
        return "ok" if manifest.exists(self.cfg) else "no_index"

    def manifest(self) -> dict[str, Any]:
        return manifest.read(self.cfg)

    def rebuild(self, allow: frozenset[str] | None = None):
        """Полная переиндексация документов, принятых в корпус.

        `allow` — имена из реестра документов; None значит «индексировать
        всё, что нашлось в каталоге» (режим без реестра).

        Сборка идёт по одной за раз: параллельные пересборки не ускоряются
        (ядра общие), а коллекция и память общие.
        """
        if not self._rebuild_lock.acquire(blocking=False):
            raise Conflict("Индексация уже идёт — дождитесь её завершения")
        try:
            return build_index(self.cfg, allow=_by_registry(allow))
        finally:
            self._rebuild_lock.release()

    def reindex_after_delete(self, path: str, allow: frozenset[str] | None = None) -> None:
        if not manifest.exists(self.cfg):
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
