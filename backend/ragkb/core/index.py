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

from ragkb.core import manifest
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

    def rebuild(self, names: frozenset[str]):
        """Полная переиндексация документов корпуса.

        `names` — имена документов из реестра: каталог не обходится, состав
        корпуса задаётся только загрузкой через интерфейс.

        Сборка идёт по одной за раз: параллельные пересборки не ускоряются
        (ядра общие), а коллекция и память общие.
        """
        if not self._rebuild_lock.acquire(blocking=False):
            raise Conflict("Индексация уже идёт — дождитесь её завершения")
        try:
            return build_index(self.cfg, names, allow_empty=True)
        finally:
            self._rebuild_lock.release()

    def reindex_after_delete(self, path: str, names: frozenset[str]) -> None:
        """Обновляет индекс после удаления документа.

        `names` — то, что осталось в реестре. Пустой реестр означает, что
        корпус опустел: индекс и манифест снимаются целиком, чтобы /health
        честно говорил «не собран».
        """
        if not manifest.exists(self.cfg):
            return
        if not names:
            shutil.rmtree(Path(self.cfg.index_dir), ignore_errors=True)
            return
        if self.cfg.store.backend.lower() == "chroma":
            remove_document(self.cfg, path)
            return
        try:
            build_index(self.cfg, names)
        except ValueError as exc:
            raise InvalidRequest(f"Не удалось пересобрать индекс: {exc}") from exc
