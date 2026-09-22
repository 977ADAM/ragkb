"""Выдача оригинала и разрешение на неё.

Файл отдаётся только по записи реестра и только из уже проверенного
дескриптора: путь из запроса не участвует вовсе. Ответы файлов и отказов идут
с `Cache-Control: no-store` — иначе браузер или прокси сохранил бы оригинал
или запомнил, что файла нет.
"""
from __future__ import annotations

import logging
from collections.abc import Iterator
from typing import Annotated, Any
from urllib.parse import quote

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse

from ragkb.api.audit import log_index_change, log_permission_change, request_id
from ragkb.api.deps.services import documents_service, downloads_service
from ragkb.api.errors import status_for
from ragkb.api.schemas.downloads import (
    DownloadPermissionResponse,
    DownloadPermissionUpdate,
    IndexPermissionResponse,
    IndexPermissionUpdate,
)
from ragkb.core.errors import RagkbError
from ragkb.services.documents import DocumentsService
from ragkb.services.downloads import CHUNK_SIZE, DownloadDescriptor, DownloadsService

log = logging.getLogger("ragkb")

router = APIRouter()

Downloads = Annotated[DownloadsService, Depends(downloads_service)]
Documents = Annotated[DocumentsService, Depends(documents_service)]

NO_STORE = {"cache-control": "no-store"}


def content_disposition(filename: str) -> str:
    """Заголовок скачивания: русские имена переживают HTTP.

    ASCII-вариант нужен старым клиентам, `filename*` — точное имя в UTF-8.
    """
    ascii_name = filename.encode("ascii", "ignore").decode("ascii").replace('"', "").strip()
    return (
        f'attachment; filename="{ascii_name or "document"}";'
        f" filename*=UTF-8''{quote(filename, safe='')}"
    )


def file_response(descriptor: DownloadDescriptor) -> StreamingResponse:
    """Потоковая отдача проверенного дескриптора.

    Файл читается порциями и закрывается на любом выходе: при завершении,
    ошибке и отмене. Длина известна заранее, поэтому ответ не буферизуется
    целиком.
    """
    return _FileResponse(
        descriptor,
        media_type=descriptor.media_type,
        headers={
            "content-disposition": content_disposition(descriptor.filename),
            "content-length": str(descriptor.size),
            **NO_STORE,
        },
    )


def _refusal(exc: RagkbError, document_id: str, request_id: str) -> JSONResponse:
    """Отказ без кэша и без путей: одинаковый для всех причин.

    `request_id` приходит от BFF: по нему строки frontend и backend
    сопоставляются, хотя посетителя в записи и не устанавливают.
    """
    log.info(
        "выдача оригинала: event=download result=refused status=%s"
        " request_id=%s document_id=%s",
        status_for(exc),
        request_id or "-",
        document_id or "-",
    )
    return JSONResponse(
        {"detail": exc.detail}, status_code=status_for(exc), headers=NO_STORE
    )


def _chunks(descriptor: DownloadDescriptor) -> Iterator[bytes]:
    try:
        while True:
            chunk = descriptor.handle.read(CHUNK_SIZE)
            if not chunk:
                return
            yield chunk
    finally:
        descriptor.close()


class _FileResponse(StreamingResponse):
    """Закрывает дескриптор при любом выходе, включая отмену до первой порции."""

    def __init__(self, descriptor: DownloadDescriptor, **kwargs: Any) -> None:
        super().__init__(_chunks(descriptor), **kwargs)
        self._descriptor = descriptor

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        try:
            await super().__call__(scope, receive, send)
        finally:
            self._descriptor.close()


@router.get("/documents/{document_id}/download")
async def download_document(document_id: str, request: Request, svc: Downloads) -> Response:
    try:
        descriptor = await svc.resolve(document_id)
    except RagkbError as exc:
        return _refusal(exc, document_id, request_id(request))
    try:
        return file_response(descriptor)
    except Exception:
        descriptor.close()
        raise


@router.head("/documents/{document_id}/download")
async def download_document_head(document_id: str, request: Request, svc: Downloads) -> Response:
    try:
        descriptor = await svc.resolve(document_id)
    except RagkbError as exc:
        return _refusal(exc, document_id, request_id(request))
    try:
        return Response(
            status_code=200,
            headers={
                "content-type": descriptor.media_type,
                "content-disposition": content_disposition(descriptor.filename),
                "content-length": str(descriptor.size),
                **NO_STORE,
            },
        )
    finally:
        descriptor.close()


@router.patch("/documents/{document_id}/download-permission")
async def set_download_permission(
    document_id: str,
    payload: DownloadPermissionUpdate,
    request: Request,
    svc: Downloads,
) -> Response:
    try:
        previous, saved = await svc.set_permission(document_id, payload.download_allowed)
    except RagkbError as exc:
        return _refusal(exc, document_id, request_id(request))
    log_permission_change(
        action="set_permission",
        document_id=saved.document_id,
        previous=previous,
        current=saved.download_allowed,
        request_id=request_id(request),
    )
    return JSONResponse(
        DownloadPermissionResponse(
            document_id=saved.document_id, download_allowed=saved.download_allowed
        ).model_dump(mode="json"),
        headers=NO_STORE,
    )


@router.patch("/documents/{document_id}/index-permission")
async def set_index_permission(
    document_id: str,
    payload: IndexPermissionUpdate,
    request: Request,
    svc: Documents,
) -> Response:
    """Участие документа в поиске: индексировать или исключить.

    Флаг применяется следующей пересборкой индекса — интерфейс говорит об этом
    прямо, а не делает вид, что поиск изменился сразу.
    """
    try:
        previous, saved = await svc.set_index_enabled(document_id, payload.index_enabled)
    except RagkbError as exc:
        return _refusal(exc, document_id, request_id(request))
    log_index_change(
        action="set_index_permission",
        document_id=saved.document_id,
        previous=previous,
        current=saved.index_enabled,
        request_id=request_id(request),
    )
    return JSONResponse(
        IndexPermissionResponse(
            document_id=saved.document_id, index_enabled=saved.index_enabled
        ).model_dump(mode="json"),
        headers=NO_STORE,
    )
