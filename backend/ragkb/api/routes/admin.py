"""Открытая страница управления базой знаний."""
from fastapi import APIRouter, Depends
from ragkb.api.deps.services import organization_service
from ragkb.core.errors import NotFound
from ragkb.services.organization import OrganizationService

router = APIRouter()


@router.get("/organization")
def organization(svc: OrganizationService = Depends(organization_service)) -> dict:
    try:
        org = svc.get()
    except NotFound:
        org = {"name": "", "id": "", "description": ""}
    return {**org, "links": {"documents": "/admin/documents", "reports": "/admin/reports"}}


@router.get("/reports")
def reports() -> dict:
    return {"status": "unavailable"}
