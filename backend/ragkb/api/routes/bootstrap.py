from uuid import UUID

from fastapi import APIRouter, Depends, Query

from ragkb.api.deps.services import bootstrap_service
from ragkb.services.bootstrap import BootstrapResponse, BootstrapService

router = APIRouter()


@router.get("/bootstrap", response_model=BootstrapResponse)
def bootstrap(
    session_id: UUID = Query(...),
    svc: BootstrapService = Depends(bootstrap_service),
) -> BootstrapResponse:
    return svc.app_start(session_id)
