"""Зависимости FastAPI: use case из app.state."""
from __future__ import annotations

from fastapi import Request

from ragkb.services.bootstrap import BootstrapService
from ragkb.services.chat_conversations import ChatConversationsService
from ragkb.services.chat_sources import IndexSources
from ragkb.services.documents import DocumentsService
from ragkb.services.feedback import FeedbackService
from ragkb.services.index import IndexService
from ragkb.services.models import ModelsService
from ragkb.services.organization import OrganizationService
from ragkb.services.search import SearchService
from ragkb.services.telemetry import TelemetryService


def _storage(request: Request):
    storage = request.app.state.storage
    storage.ensure()
    return storage


def _chats(request: Request) -> ChatConversationsService:
    cfg = request.app.state.cfg
    storage = _storage(request)
    org = OrganizationService(cfg)
    return ChatConversationsService(
        conversations=storage.conversations,
        history=storage.answer_history,
        sources=IndexSources(request.app.state.engine),
        engine=request.app.state.engine,
        resolve_model=request.app.state.models.resolve,
        require_org=org.require_id,
        window=cfg.history.window,
        persist=cfg.history.enabled,
    )


def chat_conversations_service(request: Request) -> ChatConversationsService:
    return _chats(request)


def search_service(request: Request) -> SearchService:
    return SearchService(request.app.state.engine)


def models_service(request: Request) -> ModelsService:
    return ModelsService(request.app.state.models)


def organization_service(request: Request) -> OrganizationService:
    return OrganizationService(request.app.state.cfg)


def telemetry_service(request: Request) -> TelemetryService:
    return TelemetryService(request.app.state.events)


def feedback_service(request: Request) -> FeedbackService:
    storage = _storage(request)
    if storage.feedback is None:
        raise RuntimeError("Оценки недоступны: Postgres не подключён")
    return FeedbackService(storage.feedback)


def index_service(request: Request) -> IndexService:
    return IndexService(
        request.app.state.index,
        request.app.state.engine.invalidate,
        registry=_storage(request).corpus,
    )


def documents_service(request: Request) -> DocumentsService:
    storage = _storage(request)
    return DocumentsService(
        request.app.state.cfg,
        request.app.state.index,
        request.app.state.engine.invalidate,
        registry=storage.corpus,
    )


def bootstrap_service(request: Request) -> BootstrapService:
    cfg = request.app.state.cfg
    org = OrganizationService(cfg)
    return BootstrapService(
        cfg=cfg,
        models=ModelsService(request.app.state.models),
        chats=_chats(request),
        organization=org,
        index=IndexService(
            request.app.state.index,
            request.app.state.engine.invalidate,
            registry=_storage(request).corpus,
        ),
        history_enabled=cfg.history.enabled,
    )
