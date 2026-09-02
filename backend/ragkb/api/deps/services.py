"""Зависимости FastAPI: сервисы из контейнера."""
from __future__ import annotations

from fastapi import Request

from ragkb.container import Container
from ragkb.services.bootstrap import BootstrapService
from ragkb.services.chat_conversations import ChatConversationsService
from ragkb.services.chat_sources import IndexSources
from ragkb.services.index import IndexService
from ragkb.services.models import ModelsService
from ragkb.services.organization import OrganizationService
from ragkb.services.search import SearchService
from ragkb.services.telemetry import TelemetryService


def container(request: Request) -> Container:
    return request.app.state.container


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
    c = container(request)
    c._ensure_postgres()
    return _chats(c)


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
    c._ensure_postgres()
    org = OrganizationService(c.cfg)
    return BootstrapService(
        cfg=c.cfg,
        models=ModelsService(c.models),
        chats=_chats(c),
        organization=org,
        index=IndexService(c.cfg, c.engine, c.invalidate_engine),
        history_enabled=c.history_enabled,
    )
