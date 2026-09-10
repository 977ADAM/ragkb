"""Точка входа: uvicorn ragkb.main:app."""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request

from ragkb.api.access_log import AccessLogMiddleware
from ragkb.api.errors import ragkb_error_handler, unhandled_exception
from ragkb.api.multipart import raise_multipart_part_limit
from ragkb.api.router import api_router
from ragkb.core.catalogs import make_catalog
from ragkb.core.config import Settings
from ragkb.core.engine import EngineCache
from ragkb.core.errors import RagkbError
from ragkb.core.index import ConfigIndex
from ragkb.core.logging_config import setup_logging
from ragkb.db.storage import Storage
from ragkb.services.stdout_sink import StdoutSink
from ragkb.version import __version__


@asynccontextmanager
async def lifespan(app: FastAPI):
    await app.state.storage.ready()
    yield
    await app.state.storage.dispose()


def health(request: Request) -> dict[str, str]:
    # Проверка живости смотрит на манифест индекса, а не на движок: движок
    # поднимает модель эмбеддингов, а docker healthcheck стучит сюда каждые
    # 30 секунд — загружать модель ради ответа «ok» незачем.
    return {"status": request.app.state.index.probe()}


cfg = Settings()
raise_multipart_part_limit()
setup_logging(level=cfg.logging.level, log_dir=cfg.logging.dir or None)

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
