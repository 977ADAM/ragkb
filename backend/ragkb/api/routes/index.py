import logging

from fastapi import APIRouter, Depends

from ragkb.api.deps.auth import current_user, require_admin
from ragkb.api.deps.services import index_service
from ragkb.domain.entities import User
from ragkb.services.index import IndexService

log = logging.getLogger("ragkb")

router = APIRouter()


@router.get("/status")
def status(
    user: User = Depends(current_user),
    svc: IndexService = Depends(index_service),
) -> dict:
    return svc.status()


@router.post("/index/rebuild")
def rebuild(
    user: User = Depends(require_admin),
    svc: IndexService = Depends(index_service),
) -> dict:
    result = svc.rebuild()
    log.info(
        "перестроение индекса: %s (%s файлов, %s чанков, %s с)",
        user.name,
        result["files"],
        result["chunks"],
        result["elapsed_sec"],
    )
    return result
