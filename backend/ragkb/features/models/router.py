from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ragkb.features.models.schemas import ModelInfo
from ragkb.features.models.service import ModelsService
from ragkb.platform.auth import User, current_user
from ragkb.platform.deps import models_service

router = APIRouter()


class ModelsResponse(BaseModel):
    models: list[ModelInfo]


@router.get("/models", response_model=ModelsResponse)
def list_models(
    user: User = Depends(current_user),
    svc: ModelsService = Depends(models_service),
) -> ModelsResponse:
    return ModelsResponse(models=svc.list())
