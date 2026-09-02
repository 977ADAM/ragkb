"""Вход uvicorn: create_app(cfg) и build()."""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from ragkb.api.errors import ragkb_error_handler
from ragkb.api.router import api_router
from ragkb.container import Container
from ragkb.core.config import DEFAULT_CONFIG, Config
from ragkb.core.errors import EngineUnavailable, RagkbError
from ragkb.core.logging_config import get_logger, setup_logging

log = get_logger("ragkb")


@asynccontextmanager
async def lifespan(app: FastAPI):
    c = app.state.container
    await c.ready()
    yield
    await c.dispose()


def create_app(cfg: Config) -> FastAPI:
    setup_logging(level=cfg.logging.level, log_dir=cfg.logging.dir or None)
    app = FastAPI(
        title="RAG База знаний",
        version="1.1.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    app.state.cfg = cfg
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

    app.include_router(api_router)
    return app


def build() -> FastAPI:
    return create_app(Config.load(DEFAULT_CONFIG))
