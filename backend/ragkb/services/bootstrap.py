from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from ragkb.core.config import Config
from ragkb.core.errors import NotFound
from ragkb.domain.entities import User
from ragkb.services.chat_conversations import ChatConversationsService
from ragkb.services.index import IndexService
from ragkb.services.models import ModelsService
from ragkb.services.organization import OrganizationService

log = logging.getLogger("ragkb")


class UserInfo(BaseModel):
    name: str
    email: str = ""
    groups: list[str] = Field(default_factory=list)
    is_admin: bool = False


class Capabilities(BaseModel):
    history: bool
    reindex: bool


class BootstrapResponse(BaseModel):
    session_id: str
    user: UserInfo
    organization: dict[str, str] | None = None
    models: list
    conversations: list[dict[str, Any]]
    conversations_total: int = 0
    capabilities: Capabilities
    index: dict[str, Any]


class BootstrapService:
    def __init__(
        self,
        cfg: Config,
        models: ModelsService,
        chats: ChatConversationsService,
        organization: OrganizationService,
        index: IndexService,
        history_enabled: bool,
    ):
        self.cfg = cfg
        self.models = models
        self.chats = chats
        self.organization = organization
        self.index = index
        self.history_enabled = history_enabled

    async def app_start(self, user: User, session_id: UUID) -> BootstrapResponse:
        is_admin = (
            self.cfg.auth.mode == "disabled"
            or (self.cfg.auth.mode == "session" and user.role == "admin")
            or user.in_group(self.cfg.auth.admin_group)
        )
        try:
            organization = self.organization.get()
        except NotFound:
            organization = None
        conversations: list[dict[str, Any]] = []
        total = 0
        if organization is not None:
            page = await self.chats.list_page(
                user,
                organization["id"],
                limit=50,
                offset=0,
                consistency="strong",
            )
            conversations = page["conversations"]
            total = page["total"]
        log.info("старт клиента: сессия %s, пользователь %s", session_id, user.name)
        return BootstrapResponse(
            session_id=str(session_id),
            user=UserInfo(
                name=user.name,
                email=user.email,
                groups=list(user.groups),
                is_admin=is_admin,
            ),
            organization=organization,
            models=self.models.list(),
            conversations=conversations,
            conversations_total=total,
            capabilities=Capabilities(history=self.history_enabled, reindex=is_admin),
            index=self.index.status(),
        )
