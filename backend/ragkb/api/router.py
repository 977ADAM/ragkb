"""Сборка HTTP-роутеров в один api_router."""
from fastapi import APIRouter

from ragkb.api.routes import admin, auth

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(admin.router)
