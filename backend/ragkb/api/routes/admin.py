"""HTTP-слой админки: пользователи, хаб организации, заглушка отчётов."""
from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from ragkb.features.organization.service import OrganizationService
from ragkb.platform.auth import User, require_admin
from ragkb.platform.deps import organization_service
from ragkb.platform.errors import NotFound
from ragkb.services.admin_users import AdminUsersService

router = APIRouter(dependencies=[Depends(require_admin)])

_LINKS = {"users": "/admin/users", "reports": "/admin/reports"}


class RoleBody(BaseModel):
    role: Literal["user", "admin"]


def get_admin_users(request: Request) -> AdminUsersService:
    c = request.app.state.container
    c._ensure_postgres()
    if c.accounts is None:
        raise RuntimeError("Хранилище учёток недоступно: Postgres не подключён")
    return AdminUsersService(c.accounts)


AdminUsers = Annotated[AdminUsersService, Depends(get_admin_users)]


@router.get("/users")
async def list_users(svc: AdminUsers) -> dict[str, list[dict[str, str]]]:
    return {"users": await svc.list()}


@router.patch("/users/{username}")
async def patch_user(username: str, body: RoleBody, svc: AdminUsers) -> dict[str, str]:
    return await svc.set_role(username, body.role)


@router.delete("/users/{username}", status_code=204)
async def delete_user(
    username: str,
    svc: AdminUsers,
    user: User = Depends(require_admin),
) -> None:
    await svc.delete(username, user.name)


@router.get("/organization")
def admin_organization(
    org_svc: OrganizationService = Depends(organization_service),
) -> dict:
    try:
        org = org_svc.get()
    except NotFound:
        org = {"name": "", "id": "", "description": ""}
    return {**org, "links": _LINKS}


@router.get("/reports")
def admin_reports() -> dict[str, str]:
    return {"status": "unavailable"}
