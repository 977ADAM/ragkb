from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from alembic import command
from alembic.config import Config as AlembicConfig
from fastapi import FastAPI, Request

from ragkb.api.access_log import AccessLogMiddleware
from ragkb.api.errors import ragkb_error_handler, unhandled_exception
from ragkb.api.multipart import raise_multipart_part_limit
from ragkb.api.router import api_router
from ragkb.core.catalogs import make_catalog
from ragkb.core.config import Settings
from ragkb.core.database import alembic_sync_url as alembic_sync_url
from ragkb.core.engine import EngineCache
from ragkb.core.errors import EngineUnavailable, RagkbError
from ragkb.core.index import ConfigIndex
from ragkb.core.logging_config import setup_logging
from ragkb.db.storage import Storage
from ragkb.services.stdout_sink import StdoutSink
from ragkb.version import __version__

BACKEND_ROOT = Path(__file__).resolve().parents[1]


def database_url() -> str:
    url = os.environ.get("RAGKB_TEST_DATABASE_URL") or os.environ.get(
        "RAGKB_DATABASE_URL", ""
    )
    if not url:
        raise RuntimeError(
            "Для тестов нужен Postgres: задайте RAGKB_TEST_DATABASE_URL "
            "или RAGKB_DATABASE_URL (postgresql+asyncpg://…)."
        )
    return url


def migrate() -> None:
    os.environ["RAGKB_DATABASE_URL"] = database_url()
    cfg = AlembicConfig(str(BACKEND_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_ROOT / "migrations"))
    command.upgrade(cfg, "head")


def make_app(cfg: Settings) -> FastAPI:
    raise_multipart_part_limit()
    setup_logging(level=cfg.logging.level, log_dir=cfg.logging.dir or None)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await app.state.storage.ready()
        yield
        await app.state.storage.dispose()

    def health(request: Request) -> dict[str, str]:
        try:
            request.app.state.engine()
        except EngineUnavailable:
            return {"status": "no_index"}
        return {"status": "ok"}

    app = FastAPI(
        title="RAG База знаний",
        version=__version__,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    engine = EngineCache(cfg)
    app.state.cfg = cfg
    app.state.auth = cfg.auth
    app.state.storage = Storage(cfg)
    app.state.engine = engine
    app.state.index = ConfigIndex(cfg, engine)
    app.state.models = make_catalog(cfg.llm)
    app.state.events = StdoutSink()
    app.add_exception_handler(RagkbError, ragkb_error_handler)
    app.add_exception_handler(Exception, unhandled_exception)
    app.add_middleware(AccessLogMiddleware)
    app.add_api_route("/health", health, methods=["GET"])
    app.include_router(api_router, prefix="/api/v1")
    return app
