"""HTTP-слой управления документами корпуса.

Документы попадают в базу знаний только отсюда: загрузка, удаление и
пересборка индекса. Каталог документов не обходится — файл, положенный в него
мимо интерфейса, не индексируется и в списке не появляется.
"""
from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, File, Query, Request, UploadFile

from ragkb.api.audit import log_permission_change, request_id
from ragkb.api.deps.services import documents_service
from ragkb.services.documents import MAX_UPLOAD_BYTES, DocumentsService, PermissionChange

log = logging.getLogger("ragkb")

router = APIRouter()

DocsService = Annotated[DocumentsService, Depends(documents_service)]


@router.get("/documents")
async def list_documents(svc: DocsService) -> dict:
    return await svc.list_documents()


@router.post("/documents")
async def upload_document(
    svc: DocsService,
    request: Request,
    file: UploadFile = File(...),
    index: bool = Query(True, description="Индексировать сразу после загрузки"),
    download_allowed: bool = Query(
        False, description="Разрешить скачивание оригинала документа"
    ),
) -> dict:
    # Читаем не больше лимита+1 байта: память не растёт с размером файла.
    content = await file.read(MAX_UPLOAD_BYTES + 1)
    name = file.filename or ""

    def audit(change: PermissionChange) -> None:
        """Событие пишется в момент сохранения, а не после индексации.

        Если индексация следом падает (503), разрешение в реестре уже
        изменено — и в журнале это изменение обязано остаться. Отказ самой
        записи сюда не доходит: сервис зовёт этот колбэк только после того,
        как изменение сохранено.
        """
        log_permission_change(
            action=change.action,
            document_id=change.document_id,
            previous=change.previous,
            current=change.current,
            request_id=request_id(request),
        )

    result = await svc.upload(
        name,
        content,
        index=index,
        download_allowed=download_allowed,
        on_permission_change=audit,
    )
    payload = result.payload
    if payload.get("indexed"):
        log.info("загружен документ %s (%s чанков)", name, payload["chunks"])
    else:
        log.info("принят документ %s без индексации", name)
    return payload


@router.delete("/documents/{name:path}", status_code=204)
async def delete_document(
    name: str,
    svc: DocsService,
) -> None:
    await svc.delete(name)
    log.info("удалён документ %s", name)
