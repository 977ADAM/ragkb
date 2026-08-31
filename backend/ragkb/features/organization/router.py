from fastapi import APIRouter, Depends

from ragkb.features.organization.service import OrganizationService
from ragkb.platform.auth import User, current_user
from ragkb.platform.deps import organization_service

router = APIRouter()


@router.get("/organization")
def get_organization(
    user: User = Depends(current_user),
    svc: OrganizationService = Depends(organization_service),
) -> dict[str, str]:
    return svc.get()
