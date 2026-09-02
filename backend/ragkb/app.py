"""Вход uvicorn: create_app(cfg) и build()."""
from __future__ import annotations

import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from ragkb.api.errors import ragkb_error_handler
from ragkb.api.router import api_router
from ragkb.container import Container
from ragkb.core.config import DEFAULT_CONFIG, Config
from ragkb.core.errors import EngineUnavailable, RagkbError
from ragkb.core.logging_config import get_logger, setup_logging

log = get_logger("ragkb")


class _AccessLogMiddleware:
    """Единый access-лог: метод, путь, статус, длительность, пользователь.

    Чистый ASGI, а не BaseHTTPMiddleware: не буферизует потоковые ответы
    (NDJSON генерации). Пользователь берётся из scope.state — его кладут
    Depends(current_user), поэтому он виден только на защищённых роутах.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        started = time.perf_counter()
        status = {"code": 500}

        async def _send(message):
            if message["type"] == "http.response.start":
                status["code"] = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, _send)
        finally:
            elapsed_ms = (time.perf_counter() - started) * 1000
            user = ""
            state = scope.get("state") or {}
            current = state.get("user")
            if current is not None:
                user = getattr(current, "name", "")
            log.info(
                "%s %s -> %d (%.0f ms)%s",
                scope.get("method", ""),
                scope.get("path", ""),
                status["code"],
                elapsed_ms,
                f" user={user}" if user else "",
            )


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
    app.add_middleware(_AccessLogMiddleware)

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

    @app.exception_handler(Exception)
    async def unhandled_exception(request: Request, exc: Exception) -> JSONResponse:
        log.exception(
            "необработанная ошибка %s %s", request.method, request.url.path
        )
        return JSONResponse(
            {"detail": "Внутренняя ошибка сервера"}, status_code=500
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
