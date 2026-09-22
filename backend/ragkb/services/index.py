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
    каталог мимо интерфейса, остаются в стороне, пока их не примут, а документ
    с выключенным участием в поиске в сборку не попадает. Без реестра (нет БД)
    собирается всё, что лежит в каталоге.
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
        if self._registry is None:
            raise InvalidRequest(
                "Реестр документов не подключён: задайте RAGKB_DATABASE_URL. "
                "Документы добавляются только загрузкой через страницу «Документы»."
            )
        if not await self._registry.names():
            raise InvalidRequest(
                "В корпусе нет документов: загрузите их на странице «Документы»"
            )
        names = frozenset(await self._registry.index_names())
        try:
            report = await asyncio.to_thread(self._index.rebuild, names)
        except (ValueError, FileNotFoundError) as exc:
            raise InvalidRequest(str(exc)) from exc
        self._invalidate()
        return {
            "files": report.files,
            "chunks": report.chunks,
            "skipped": report.skipped,
            "elapsed_sec": round(report.elapsed, 1),
        }
