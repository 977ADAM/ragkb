"""Организация установки."""
from __future__ import annotations

from ragkb.core.config import Settings
from ragkb.core.errors import NotFound


class OrganizationService:
    def __init__(self, cfg: Settings):
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
