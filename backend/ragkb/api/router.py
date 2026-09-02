"""Сборка HTTP-роутеров в один api_router."""
from fastapi import APIRouter

from ragkb.api.routes import admin, auth, users

api_router = APIRouter()
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(admin.router, prefix="/admin", tags=["admin"])
api_router.include_router(users.router, prefix="/users", tags=["users"])
