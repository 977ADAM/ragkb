"""Зависимости FastAPI: use case из app.state."""
from __future__ import annotations

from pathlib import Path

from fastapi import Request

from ragkb.core.catalogs import embedding_models
from ragkb.services.ask import AskService
from ragkb.services.bootstrap import BootstrapService
from ragkb.services.documents import DocumentsService
from ragkb.services.downloads import DownloadsService
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
    # Реестр берём у хранилища напрямую: без базы он уже None, и подготовка
    # кандидатов просто не находит документов — обычный ответ работает.
    return AskService(
        request.app.state.engine,
        request.app.state.models.resolve,
        registry=request.app.state.storage.corpus,
        docs_dir=request.app.state.cfg.docs_dir,
    )


def search_service(request: Request) -> SearchService:
    return SearchService(request.app.state.engine)


def _embedding_models(request: Request):
    """Провайдер списка моделей эмбеддингов: тот же Ollama, что считает векторы."""
    return lambda: embedding_models(request.app.state.cfg)


def models_service(request: Request) -> ModelsService:
    return ModelsService(
        request.app.state.models, embedding_models=_embedding_models(request)
    )


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


def downloads_service(request: Request) -> DownloadsService:
    """Выдача оригинала: реестр решает, что и при каком разрешении отдавать."""
    storage = _storage(request)
    return DownloadsService(
        Path(request.app.state.cfg.docs_dir), registry=storage.corpus
    )


def settings_service(request: Request) -> SettingsService:
    return SettingsService(
        request.app.state.cfg,
        request.app.state.engine.invalidate,
        index=request.app.state.index,
        models=_embedding_models(request),
    )


def bootstrap_service(request: Request) -> BootstrapService:
    cfg = request.app.state.cfg
    org = OrganizationService(cfg)
    return BootstrapService(
        models=ModelsService(
            request.app.state.models, embedding_models=_embedding_models(request)
        ),
        organization=org,
        index=IndexService(
            request.app.state.index,
            request.app.state.engine.invalidate,
            registry=_storage(request).corpus,
        ),
    )
