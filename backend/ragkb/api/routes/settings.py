"""Страница настроек: описание полей и применение правок."""
import logging

from fastapi import APIRouter, Depends

from ragkb.api.deps.services import settings_service
from ragkb.api.schemas.settings import SettingsUpdate
from ragkb.services.settings import SettingsService

log = logging.getLogger("ragkb")

router = APIRouter()


@router.get("/settings")
def settings(svc: SettingsService = Depends(settings_service)) -> dict:
    return svc.describe()


@router.put("/settings")
def update_settings(
    patch: SettingsUpdate,
    svc: SettingsService = Depends(settings_service),
) -> dict:
    result = svc.update(patch.values, patch.reset)
    if result["changed"]:
        log.info("настройки изменены: %s", ", ".join(result["changed"]))
    return result
