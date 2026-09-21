from __future__ import annotations

from typing import Any
from uuid import UUID
from pydantic import BaseModel

from ragkb.core.errors import NotFound
from ragkb.services.index import IndexService
from ragkb.services.models import ModelsService
from ragkb.services.organization import OrganizationService
from ragkb.version import __version__


class BootstrapResponse(BaseModel):
    session_id: str
    version: str = __version__
    organization: dict[str, str] | None = None
    models: list
    index: dict[str, Any]


class BootstrapService:
    def __init__(self, models: ModelsService, organization: OrganizationService, index: IndexService):
        self.models = models
        self.organization = organization
        self.index = index

    def app_start(self, session_id: UUID) -> BootstrapResponse:
        try:
            organization = self.organization.get()
        except NotFound:
            organization = None
        return BootstrapResponse(
            session_id=str(session_id), organization=organization,
            models=self.models.list(), index=self.index.status(),
        )
