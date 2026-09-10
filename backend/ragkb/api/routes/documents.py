"""HTTP-слой управления документами корпуса (админ).

Документы попадают в базу знаний только отсюда: файлы, положенные в каталог
корпуса мимо интерфейса, видны в списке как «вне корпуса» и индексируются
лишь после явного принятия.
"""
from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, File, Query, UploadFile

from ragkb.api.deps.auth import require_admin
from ragkb.api.deps.services import documents_service
from ragkb.api.schemas.documents import AcceptRequest
from ragkb.domain.entities import User
from ragkb.services.documents import MAX_UPLOAD_BYTES, DocumentsService

log = logging.getLogger("ragkb")

router = APIRouter(dependencies=[Depends(require_admin)])

DocsService = Annotated[DocumentsService, Depends(documents_service)]


@router.get("/documents")
async def list_documents(svc: DocsService) -> dict:
    return await svc.list_documents()


@router.post("/documents")
async def upload_document(
    svc: DocsService,
    user: User = Depends(require_admin),
    file: UploadFile = File(...),
    index: bool = Query(True, description="Индексировать сразу после загрузки"),
) -> dict:
    # Читаем не больше лимита+1 байта: память не растёт с размером файла.
    content = await file.read(MAX_UPLOAD_BYTES + 1)
    name = file.filename or ""
    result = await svc.upload(name, content, user.name, index=index)
    if result.get("indexed"):
        log.info(
            "админ %s: загружен документ %s (%s чанков)", user.name, name, result["chunks"]
        )
    else:
        log.info("админ %s: принят документ %s без индексации", user.name, name)
    return result


@router.post("/documents/accept")
async def accept_documents(
    body: AcceptRequest,
    svc: DocsService,
    user: User = Depends(require_admin),
) -> dict:
    result = await svc.accept(body.names, user.name)
    log.info(
        "админ %s: принято в корпус документов %s (%s чанков)",
        user.name,
        len(result["accepted"]),
        result["chunks"],
    )
    return result


@router.delete("/documents/{name:path}", status_code=204)
async def delete_document(
    name: str,
    svc: DocsService,
    user: User = Depends(require_admin),
) -> None:
    await svc.delete(name)
    log.info("админ %s: удалён документ %s", user.name, name)
