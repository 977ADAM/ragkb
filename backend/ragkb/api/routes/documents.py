"""HTTP-слой управления документами корпуса.

Документы попадают в базу знаний только отсюда: загрузка, удаление и
пересборка индекса. Каталог документов не обходится — файл, положенный в него
мимо интерфейса, не индексируется и в списке не появляется.
"""
from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, File, Query, UploadFile

from ragkb.api.deps.services import documents_service
from ragkb.services.documents import MAX_UPLOAD_BYTES, DocumentsService

log = logging.getLogger("ragkb")

router = APIRouter()

DocsService = Annotated[DocumentsService, Depends(documents_service)]


@router.get("/documents")
async def list_documents(svc: DocsService) -> dict:
    return await svc.list_documents()


@router.post("/documents")
async def upload_document(
    svc: DocsService,
    file: UploadFile = File(...),
    index: bool = Query(True, description="Индексировать сразу после загрузки"),
) -> dict:
    # Читаем не больше лимита+1 байта: память не растёт с размером файла.
    content = await file.read(MAX_UPLOAD_BYTES + 1)
    name = file.filename or ""
    result = await svc.upload(name, content, index=index)
    if result.get("indexed"):
        log.info(
            "загружен документ %s (%s чанков)", name, result["chunks"]
        )
    else:
        log.info("принят документ %s без индексации", name)
    return result


@router.delete("/documents/{name:path}", status_code=204)
async def delete_document(
    name: str,
    svc: DocsService,
) -> None:
    await svc.delete(name)
    log.info("удалён документ %s", name)
