"""HTTP-слой управления документами корпуса (админ)."""
from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, File, UploadFile

from ragkb.api.deps.auth import require_admin
from ragkb.api.deps.services import documents_service
from ragkb.services.documents import MAX_UPLOAD_BYTES, DocumentsService

log = logging.getLogger("ragkb")

router = APIRouter(dependencies=[Depends(require_admin)])

DocsService = Annotated[DocumentsService, Depends(documents_service)]


@router.get("/documents")
def list_documents(svc: DocsService) -> dict:
    return svc.list_documents()


@router.post("/documents")
async def upload_document(
    svc: DocsService,
    file: UploadFile = File(...),
) -> dict:
    # Читаем не больше лимита+1 байта: память не растёт с размером файла.
    content = await file.read(MAX_UPLOAD_BYTES + 1)
    result = svc.upload(file.filename or "", content)
    log.info("админ: загружен документ %s (%s чанков)", file.filename, result["chunks"])
    return result


@router.delete("/documents/{name}", status_code=204)
def delete_document(name: str, svc: DocsService) -> None:
    svc.delete(name)
    log.info("админ: удалён документ %s", name)
