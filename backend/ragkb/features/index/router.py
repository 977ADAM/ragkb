from fastapi import APIRouter, Depends

from ragkb.features.index.service import IndexService
from ragkb.platform.auth import User, current_user, require_admin
from ragkb.platform.deps import index_service

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
    return svc.rebuild()
