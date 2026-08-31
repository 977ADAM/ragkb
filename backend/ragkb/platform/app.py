"""Вход uvicorn: create_app(cfg) и build()."""
from __future__ import annotations

import logging

from fastapi import FastAPI

from ragkb.core.config import DEFAULT_CONFIG, Config
from ragkb.features.bootstrap.router import router as bootstrap_router
from ragkb.features.chat_conversations.router import router as chats_router
from ragkb.features.index.router import router as index_router
from ragkb.features.models.router import router as models_router
from ragkb.features.organization.router import router as organization_router
from ragkb.features.search.router import router as search_router
from ragkb.features.telemetry.router import router as telemetry_router
from ragkb.platform.container import Container
from ragkb.platform.errors import EngineUnavailable, RagkbError, ragkb_error_handler

log = logging.getLogger("ragkb")


def create_app(cfg: Config) -> FastAPI:
    logging.basicConfig(level=logging.INFO)
    app = FastAPI(
        title="RAG База знаний",
        version="1.1.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.auth = cfg.auth
    app.state.container = Container(cfg)
    app.add_exception_handler(RagkbError, ragkb_error_handler)

    if cfg.auth.mode == "disabled":
        log.warning(
            "аутентификация выключена (auth.mode: disabled). "
            "Все запросы выполняются от имени «anonymous»."
        )
    if cfg.llm.available and cfg.llm.model not in {
        e.get("name", "") for e in cfg.llm.available
    }:
        log.warning(
            "llm.model «%s» отсутствует в llm.available. "
            "Список моделей разойдётся с моделью по умолчанию.",
            cfg.llm.model,
        )

    @app.get("/health")
    def health() -> dict[str, str]:
        try:
            app.state.container.engine()
        except EngineUnavailable:
            return {"status": "no_index"}
        return {"status": "ok"}

    app.include_router(models_router)
    app.include_router(search_router)
    app.include_router(organization_router)
    app.include_router(chats_router)
    app.include_router(telemetry_router)
    app.include_router(bootstrap_router)
    app.include_router(index_router)
    return app


def build() -> FastAPI:
    return create_app(Config.load(DEFAULT_CONFIG))
