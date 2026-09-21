from fastapi import APIRouter, Depends

from ragkb.api.deps.services import organization_service
from ragkb.services.organization import OrganizationService

router = APIRouter()


@router.get("/organization")
def get_organization(
    svc: OrganizationService = Depends(organization_service),
) -> dict[str, str]:
    return svc.get()
