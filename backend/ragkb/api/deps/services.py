"""Зависимости FastAPI: use case из app.state."""
from __future__ import annotations

from fastapi import Request

from ragkb.services.ask import AskService
from ragkb.services.bootstrap import BootstrapService
from ragkb.services.documents import DocumentsService
from ragkb.services.index import IndexService
from ragkb.services.models import ModelsService
from ragkb.services.organization import OrganizationService
from ragkb.services.search import SearchService
from ragkb.services.settings import SettingsService
from ragkb.services.telemetry import TelemetryService


def _storage(request: Request):
    storage = request.app.state.storage
    storage.ensure()
    return storage


def ask_service(request: Request) -> AskService:
    return AskService(request.app.state.engine, request.app.state.models.resolve)


def search_service(request: Request) -> SearchService:
    return SearchService(request.app.state.engine)


def models_service(request: Request) -> ModelsService:
    return ModelsService(request.app.state.models)


def organization_service(request: Request) -> OrganizationService:
    return OrganizationService(request.app.state.cfg)


def telemetry_service(request: Request) -> TelemetryService:
    return TelemetryService(request.app.state.events)


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


def settings_service(request: Request) -> SettingsService:
    return SettingsService(
        request.app.state.cfg,
        request.app.state.engine.invalidate,
        index=request.app.state.index,
    )


def bootstrap_service(request: Request) -> BootstrapService:
    cfg = request.app.state.cfg
    org = OrganizationService(cfg)
    return BootstrapService(
        models=ModelsService(request.app.state.models),
        organization=org,
        index=IndexService(
            request.app.state.index,
            request.app.state.engine.invalidate,
            registry=_storage(request).corpus,
        ),
    )
