import logging

from fastapi import APIRouter, Depends

from ragkb.api.deps.services import index_service
from ragkb.services.index import IndexService

log = logging.getLogger("ragkb")

router = APIRouter()


@router.get("/status")
def status(
    svc: IndexService = Depends(index_service),
) -> dict:
    return svc.status()


@router.post("/index/rebuild")
async def rebuild(
    svc: IndexService = Depends(index_service),
) -> dict:
    result = await svc.rebuild()
    log.info(
        "перестроение индекса: (%s файлов, %s чанков, %s с)",
        result["files"],
        result["chunks"],
        result["elapsed_sec"],
    )
    return result
