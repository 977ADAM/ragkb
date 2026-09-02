from uuid import UUID

from fastapi import APIRouter, Depends, Query

from ragkb.api.deps.auth import current_user
from ragkb.api.deps.services import bootstrap_service
from ragkb.domain.entities import User
from ragkb.services.bootstrap import BootstrapResponse, BootstrapService

router = APIRouter()


@router.get("/bootstrap", response_model=BootstrapResponse)
async def bootstrap(
    session_id: UUID = Query(...),
    user: User = Depends(current_user),
    svc: BootstrapService = Depends(bootstrap_service),
) -> BootstrapResponse:
    return await svc.app_start(user, session_id)
