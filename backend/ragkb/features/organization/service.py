"""Организация установки."""
from __future__ import annotations

from ragkb.core.config import Config
from ragkb.platform.errors import NotFound


class OrganizationService:
    def __init__(self, cfg: Config):
        self.cfg = cfg

    def get(self) -> dict[str, str]:
        org = self.cfg.organization
        if not org.name:
            raise NotFound("Организация не найдена")
        return {
            "id": org.id or org.name,
            "name": org.name,
            "description": org.description,
        }

    def require_id(self, organization_id: str) -> None:
        configured = self.cfg.organization.id or self.cfg.organization.name
        if not configured or organization_id != configured:
            raise NotFound("Организация не найдена")
