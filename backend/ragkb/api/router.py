"""Публичные HTTP-маршруты приложения."""
from fastapi import APIRouter
from ragkb.api.routes import (
    admin,
    ask,
    bootstrap,
    documents,
    downloads,
    index,
    models,
    organization,
    search,
    settings,
    telemetry,
)

api_router = APIRouter()
api_router.include_router(admin.router, prefix="/admin")
api_router.include_router(documents.router, prefix="/admin")
api_router.include_router(settings.router, prefix="/admin")
for module in (ask, models, search, organization, telemetry, bootstrap, index, downloads):
    api_router.include_router(module.router)
