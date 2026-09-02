from fastapi import APIRouter, Depends

from ragkb.api.deps.auth import current_user
from ragkb.api.deps.services import organization_service
from ragkb.domain.entities import User
from ragkb.services.organization import OrganizationService

router = APIRouter()


@router.get("/organization")
def get_organization(
    user: User = Depends(current_user),
    svc: OrganizationService = Depends(organization_service),
) -> dict[str, str]:
    return svc.get()
