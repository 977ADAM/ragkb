"""Точка входа: uvicorn ragkb.main:build --factory."""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from ragkb.api.access_log import AccessLogMiddleware
from ragkb.api.errors import ragkb_error_handler, unhandled_exception
from ragkb.api.multipart import raise_multipart_part_limit
from ragkb.api.router import api_router
from ragkb.core.config import Settings
from ragkb.core.database import make_engine, make_session_factory, needs_database
from ragkb.core.errors import EngineUnavailable, RagkbError
from ragkb.core.logging_config import get_logger, setup_logging
from ragkb.core.pipeline import RAGPipeline
from ragkb.core.ports import AnswerEngine
from ragkb.db.repos.auth import PostgresAccounts
from ragkb.db.repos.ephemeral_history import EphemeralHistory
from ragkb.db.repos.feedback import PostgresFeedback
from ragkb.db.repos.postgres_history import PostgresHistory
from ragkb.services.models_ollama import OllamaCatalog
from ragkb.services.models_openai import OpenAICatalog
from ragkb.services.models_static import StaticCatalog
from ragkb.services.stdout_sink import StdoutSink
from ragkb.version import __version__

log = get_logger("ragkb")


class Container:
    """Композиционный корень: хранилища, каталог моделей, ленивый RAGPipeline."""

    def __init__(
        self,
        cfg: Settings,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
    ):
        self.cfg = cfg
        self._engine: AnswerEngine | None = None
        self.engine_obj: AsyncEngine | None = None
        self._database_url = ""
        self.conversations: EphemeralHistory | PostgresHistory | None = None
        self.answer_history: EphemeralHistory | PostgresHistory | None = None
        self.accounts: PostgresAccounts | None = None
        self.feedback: PostgresFeedback | None = None
        self._bind_storage(session_factory)
        self.models = _model_catalog(cfg.llm)
        self.events = StdoutSink()
        self.history_window = cfg.history.window
        self.history_enabled = cfg.history.enabled

    def _bind_storage(
        self,
        session_factory: async_sessionmaker[AsyncSession] | None,
    ) -> None:
        if session_factory is not None:
            self._bind_postgres(session_factory)
            return
        if needs_database(self.cfg):
            if not self.cfg.database_url:
                raise RuntimeError("Задайте RAGKB_DATABASE_URL")
            # Engine — в ready() / первом запросе, на цикле TestClient.
            self._database_url = self.cfg.database_url
            return
        ephemeral = EphemeralHistory()
        self.conversations = ephemeral
        self.answer_history = ephemeral

    def _bind_postgres(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        if self.cfg.history.enabled:
            history = PostgresHistory(
                session_factory, retention_days=self.cfg.history.retention_days
            )
            self.conversations = history
            self.answer_history = history
        else:
            ephemeral = EphemeralHistory()
            self.conversations = ephemeral
            self.answer_history = ephemeral
        self.accounts = PostgresAccounts(session_factory)
        self.feedback = PostgresFeedback(session_factory)

    def _ensure_postgres(self) -> None:
        if self._database_url and self.engine_obj is None:
            self.engine_obj = make_engine(self._database_url)
            self._bind_postgres(make_session_factory(self.engine_obj))

    async def ready(self) -> None:
        self._ensure_postgres()
        if isinstance(self.conversations, PostgresHistory):
            await self.conversations.ready()
        if self.accounts is not None:
            await self.accounts.ready()

    async def dispose(self) -> None:
        if self.engine_obj is not None:
            await self.engine_obj.dispose()
            self.engine_obj = None

    def engine(self) -> AnswerEngine:
        if self._engine is None:
            try:
                self._engine = RAGPipeline(self.cfg)
            except Exception as exc:
                raise EngineUnavailable(str(exc)) from exc
        return self._engine

    def invalidate_engine(self) -> None:
        self._engine = None


def _model_catalog(llm: Settings.LLMConfig):
    kind = llm.backend.lower()
    if kind in {"openai", "vllm", "openai-compatible"}:
        return OpenAICatalog(llm)
    if kind == "ollama":
        return OllamaCatalog(llm)
    return StaticCatalog(llm)


@asynccontextmanager
async def lifespan(app: FastAPI):
    container = app.state.container
    await container.ready()
    yield
    await container.dispose()


def health(request: Request) -> dict[str, str]:
    try:
        request.app.state.container.engine()
    except EngineUnavailable:
        return {"status": "no_index"}
    return {"status": "ok"}


def _warn_misconfig(cfg: Settings) -> None:
    if cfg.auth.mode == "disabled":
        log.warning(
            "аутентификация выключена (auth.mode: disabled). "
            "Все запросы выполняются от имени «anonymous»."
        )
    names = {entry.get("name", "") for entry in cfg.llm.available}
    if cfg.llm.available and cfg.llm.model not in names:
        log.warning(
            "llm.model «%s» отсутствует в llm.available. "
            "Список моделей разойдётся с моделью по умолчанию.",
            cfg.llm.model,
        )


def create_app(cfg: Settings) -> FastAPI:
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
    app.state.cfg = cfg
    app.state.auth = cfg.auth
    app.state.container = Container(cfg)

    app.add_exception_handler(RagkbError, ragkb_error_handler)
    app.add_exception_handler(Exception, unhandled_exception)
    app.add_middleware(AccessLogMiddleware)
    app.add_api_route("/health", health, methods=["GET"])
    app.include_router(api_router, prefix="/api/v1")

    _warn_misconfig(cfg)
    return app


def build() -> FastAPI:
    return create_app(Settings())
