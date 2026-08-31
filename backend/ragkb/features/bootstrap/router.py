from uuid import UUID

from fastapi import APIRouter, Depends, Query

from ragkb.features.bootstrap.service import BootstrapResponse, BootstrapService
from ragkb.platform.auth import User, current_user
from ragkb.platform.deps import bootstrap_service

router = APIRouter()


@router.get("/bootstrap", response_model=BootstrapResponse)
def bootstrap(
    session_id: UUID = Query(...),
    user: User = Depends(current_user),
    svc: BootstrapService = Depends(bootstrap_service),
) -> BootstrapResponse:
    return svc.app_start(user, session_id)
