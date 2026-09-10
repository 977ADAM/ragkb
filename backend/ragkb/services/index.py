from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

from ragkb.core.errors import EngineUnavailable, InvalidRequest
from ragkb.core.ports import IndexEngine
from ragkb.domain.ports import DocumentRegistry


class IndexService:
    """Пересборка индекса корпуса.

    Реестр документов решает, что вообще индексировать: файлы, положенные в
    каталог мимо интерфейса, остаются в стороне, пока их не примут. Без
    реестра (нет БД) собирается всё, что лежит в каталоге.
    """

    def __init__(
        self,
        index: IndexEngine,
        invalidate: Callable[[], None],
        registry: DocumentRegistry | None = None,
    ):
        self._index = index
        self._invalidate = invalidate
        self._registry = registry

    def status(self) -> dict[str, Any]:
        try:
            return {"status": "ok", **self._index.stats()}
        except EngineUnavailable as exc:
            return {"status": "no_index", "detail": exc.detail}

    async def rebuild(self) -> dict[str, Any]:
        allow = None
        if self._registry is not None:
            allow = frozenset(await self._registry.names())
        # Индексация синхронная и тяжёлая: уводим её с цикла событий, иначе
        # на время сборки перестают отвечать все остальные запросы.
        try:
            report = await asyncio.to_thread(self._index.rebuild, allow)
        except (ValueError, FileNotFoundError) as exc:
            # «Ни один файл не принят в корпус» — это ошибка запроса, а не сбой
            # сервиса: администратору нужно объяснение, что делать дальше.
            raise InvalidRequest(str(exc)) from exc
        self._invalidate()
        return {
            "files": report.files,
            "chunks": report.chunks,
            "skipped": report.skipped,
            "excluded": report.excluded,
            "elapsed_sec": round(report.elapsed, 1),
        }
