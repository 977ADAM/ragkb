"""Публичные HTTP-маршруты приложения."""
from fastapi import APIRouter
from ragkb.api.routes import admin, ask, bootstrap, documents, index, models, organization, search, telemetry

api_router = APIRouter()
api_router.include_router(admin.router, prefix="/admin")
api_router.include_router(documents.router, prefix="/admin")
for module in (ask, models, search, organization, telemetry, bootstrap, index):
    api_router.include_router(module.router)
