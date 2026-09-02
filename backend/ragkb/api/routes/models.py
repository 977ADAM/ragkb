from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ragkb.api.deps.auth import current_user
from ragkb.api.deps.services import models_service
from ragkb.domain.entities import User
from ragkb.services.models import ModelsService
from ragkb.services.models_schemas import ModelInfo

router = APIRouter()


class ModelsResponse(BaseModel):
    models: list[ModelInfo]


@router.get("/models", response_model=ModelsResponse)
def list_models(
    user: User = Depends(current_user),
    svc: ModelsService = Depends(models_service),
) -> ModelsResponse:
    return ModelsResponse(models=svc.list())
