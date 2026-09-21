from __future__ import annotations

import hashlib
import math
from collections.abc import Iterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from langchain_core.embeddings import Embeddings
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from pydantic import Field

from ragkb.api.access_log import AccessLogMiddleware
from ragkb.api.errors import ragkb_error_handler, unhandled_exception
from ragkb.api.multipart import raise_multipart_part_limit
from ragkb.api.router import api_router
from ragkb.core.catalogs import make_catalog
from ragkb.core.config import Settings
from ragkb.core.database import alembic_sync_url as alembic_sync_url
from ragkb.core.engine import EngineCache
from ragkb.core.errors import RagkbError
from ragkb.core.index import ConfigIndex
from ragkb.core.logging_config import setup_logging
from ragkb.core.text import tokenize
from ragkb.db.storage import Storage
from ragkb.services.stdout_sink import StdoutSink
from ragkb.version import __version__

BACKEND_ROOT = Path(__file__).resolve().parents[1]


def make_app(cfg: Settings) -> FastAPI:
    raise_multipart_part_limit()
    setup_logging(level=cfg.logging.level, log_dir=cfg.logging.dir or None)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await app.state.storage.ready()
        yield
        await app.state.storage.dispose()

    def health(request: Request) -> dict[str, str]:
        return {"status": request.app.state.index.probe()}

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


class KeywordEmbeddings(Embeddings):
    """Векторы по словам текста: косинус отражает пересечение лексики.

    Нужны там, где важно, чтобы поиск нашёл правильный документ:
    `DeterministicFakeEmbedding` даёт случайные направления, и близость по
    ней ничего не значит. Хэширование слов в координаты сохраняет смысл
    сравнения для любого текста, без словаря и без сети.
    """

    def __init__(self, dim: int = 256):
        self.dim = dim

    def _vector(self, text: str) -> list[float]:
        vector = [0.0] * self.dim
        for token in tokenize(text):
            index = int(hashlib.sha1(token.encode("utf-8")).hexdigest()[:8], 16) % self.dim
            vector[index] += 1.0
        norm = math.sqrt(sum(value * value for value in vector)) or 1.0
        return [value / norm for value in vector]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._vector(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vector(text)


class ScriptedChatModel(BaseChatModel):
    """Модель с заданными ответами: тесты цепочки без обращения к серверу."""

    responses: list[str] = Field(default_factory=list)
    calls: list[list[Any]] = Field(default_factory=list)

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        self.calls.append(list(messages))
        index = min(len(self.calls) - 1, len(self.responses) - 1)
        return ChatResult(generations=[ChatGeneration(message=AIMessage(self.responses[index]))])

    def _stream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any | None = None,
        **kwargs: Any,
    ) -> Iterator[ChatGenerationChunk]:
        answer = self._generate(messages).generations[0].message.content
        for piece in str(answer).split(" "):
            yield ChatGenerationChunk(message=AIMessageChunk(content=piece + " "))
