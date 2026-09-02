"""Сборка HTTP-роутеров в один api_router."""
from fastapi import APIRouter

from ragkb.api.routes import (
    admin,
    auth,
    bootstrap,
    chat_conversations,
    index,
    models,
    organization,
    search,
    telemetry,
    users,
)

api_router = APIRouter()
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(admin.router, prefix="/admin", tags=["admin"])
api_router.include_router(users.router, prefix="/users", tags=["users"])
api_router.include_router(models.router)
api_router.include_router(search.router)
api_router.include_router(organization.router)
api_router.include_router(chat_conversations.router)
api_router.include_router(telemetry.router)
api_router.include_router(bootstrap.router)
api_router.include_router(index.router)
