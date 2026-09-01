"""Зависимости FastAPI: сервисы слайсов из контейнера."""
from __future__ import annotations

from fastapi import Request

from ragkb.features.auth.service import AuthService
from ragkb.features.bootstrap.service import BootstrapService
from ragkb.features.chat_conversations.service import ChatConversationsService
from ragkb.features.chat_conversations.sources import IndexSources
from ragkb.features.index.service import IndexService
from ragkb.features.models.service import ModelsService
from ragkb.features.organization.service import OrganizationService
from ragkb.features.search.service import SearchService
from ragkb.features.telemetry.service import TelemetryService
from ragkb.platform.container import Container


def container(request: Request) -> Container:
    return request.app.state.container


def auth_service(request: Request) -> AuthService:
    return AuthService(container(request).accounts)


def _chats(c: Container) -> ChatConversationsService:
    org = OrganizationService(c.cfg)
    return ChatConversationsService(
        conversations=c.conversations,
        history=c.answer_history,
        sources=IndexSources(c.engine),
        engine=c.engine,
        resolve_model=c.models.resolve,
        require_org=org.require_id,
        window=c.history_window,
        llm_cfg=c.cfg.llm,
    )


def chat_conversations_service(request: Request) -> ChatConversationsService:
    return _chats(container(request))


def search_service(request: Request) -> SearchService:
    return SearchService(container(request).engine)


def models_service(request: Request) -> ModelsService:
    return ModelsService(container(request).models)


def organization_service(request: Request) -> OrganizationService:
    return OrganizationService(container(request).cfg)


def telemetry_service(request: Request) -> TelemetryService:
    return TelemetryService(container(request).events)


def index_service(request: Request) -> IndexService:
    c = container(request)
    return IndexService(c.cfg, c.engine, c.invalidate_engine)


def bootstrap_service(request: Request) -> BootstrapService:
    c = container(request)
    org = OrganizationService(c.cfg)
    return BootstrapService(
        cfg=c.cfg,
        models=ModelsService(c.models),
        chats=_chats(c),
        organization=org,
        index=IndexService(c.cfg, c.engine, c.invalidate_engine),
        history_enabled=c.history_enabled,
    )
