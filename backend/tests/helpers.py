from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Iterator
from contextlib import asynccontextmanager
from dataclasses import replace
from pathlib import Path
from typing import Any
from uuid import uuid4

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
from ragkb.core.settings import apply_overrides, read_overrides
from ragkb.core.text import tokenize
from ragkb.db.storage import Storage
from ragkb.domain.entities import ORIGIN_UI, CorpusDocument, RecordOutcome
from ragkb.services.stdout_sink import StdoutSink
from ragkb.version import __version__

BACKEND_ROOT = Path(__file__).resolve().parents[1]


def make_app(cfg: Settings) -> FastAPI:
    apply_overrides(cfg, read_overrides(cfg.settings_file))
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


class MemoryRegistry:
    """Реестр документов в памяти — замена Postgres в тестах сервисов.

    Повторяет контракт SQL-адаптера: идентификатор переживает замену файла,
    новое имя получает свой, а разрешение на выдачу оригинала берётся из
    явного аргумента записи.
    """

    def __init__(self) -> None:
        self.rows: dict[str, CorpusDocument] = {}

    def add(
        self,
        cfg: Settings,
        *names: str,
        download_allowed: bool = False,
        index_enabled: bool = True,
    ) -> MemoryRegistry:
        """Заводит в реестре файлы, которые уже лежат в каталоге корпуса."""
        for name in names or tuple(p.name for p in Path(cfg.docs_dir).iterdir()):
            data = (Path(cfg.docs_dir) / name).read_bytes()
            self.rows[name] = CorpusDocument(
                name=name,
                document_id=str(uuid4()),
                origin=ORIGIN_UI,
                uploaded_at="2026-09-10T00:00:00+00:00",
                size=len(data),
                sha256=hashlib.sha256(data).hexdigest(),
                download_allowed=download_allowed,
                index_enabled=index_enabled,
            )
        return self

    def index_files(self) -> frozenset[str]:
        """Синхронный помощник тестов: имена документов, участвующих в поиске.

        Метод реестра `index_names` асинхронный — как и весь порт; здесь нужен
        такой же набор, но без запуска цикла событий.
        """
        return frozenset(name for name, doc in self.rows.items() if doc.index_enabled)

    async def names(self) -> set[str]:
        return set(self.rows)

    async def index_names(self) -> set[str]:
        return set(self.index_files())

    async def list_all(self) -> list[CorpusDocument]:
        return list(self.rows.values())

    async def get_by_id(self, document_id: str) -> CorpusDocument | None:
        if not document_id:
            return None
        return next(
            (doc for doc in self.rows.values() if doc.document_id == document_id), None
        )

    async def record(
        self,
        name: str,
        *,
        origin: str = ORIGIN_UI,
        uploaded_by: str = "",
        size: int = 0,
        sha256: str = "",
        download_allowed: bool = False,
        index_enabled: bool = True,
    ) -> RecordOutcome:
        previous = self.rows.get(name)
        saved = CorpusDocument(
            name=name,
            document_id=previous.document_id if previous else str(uuid4()),
            origin=origin,
            uploaded_by=uploaded_by,
            uploaded_at="2026-09-10T00:00:00+00:00",
            size=size,
            sha256=sha256,
            download_allowed=download_allowed,
            index_enabled=index_enabled,
        )
        self.rows[name] = saved
        return RecordOutcome(
            created=previous is None,
            previous_download_allowed=previous.download_allowed if previous else False,
            document=saved,
            previous_index_enabled=previous.index_enabled if previous else True,
        )

    async def set_download_allowed(
        self, document_id: str, allowed: bool
    ) -> tuple[bool, CorpusDocument] | None:
        for name, document in self.rows.items():
            if document.document_id == document_id:
                saved = replace(document, download_allowed=bool(allowed))
                self.rows[name] = saved
                return document.download_allowed, saved
        return None

    async def set_index_enabled(
        self, document_id: str, enabled: bool
    ) -> tuple[bool, CorpusDocument] | None:
        for name, document in self.rows.items():
            if document.document_id == document_id:
                saved = replace(document, index_enabled=bool(enabled))
                self.rows[name] = saved
                return document.index_enabled, saved
        return None

    async def forget(self, name: str) -> bool:
        return self.rows.pop(name, None) is not None


def corpus_names(cfg: Settings) -> frozenset[str]:
    """Имена файлов каталога — тест объявляет их корпусом вместо реестра.

    В приложении состав корпуса задаёт реестр; в тестах, где реестра нет,
    его роль играет этот список.
    """
    return frozenset(p.name for p in Path(cfg.docs_dir).iterdir() if p.is_file())


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
    """Модель с заданными ответами: тесты цепочки без обращения к серверу.

    `responses` принимает и строки (обычный текст), и готовые `AIMessage` с
    `tool_calls`. Поток отдаёт текст по словам, а аргументы инструмента —
    частями, как это делает настоящий сервер: так проверяется сборка
    `tool_call_chunks` до полных аргументов.

    `bound_tools` фиксирует, дошли ли инструменты до вызова модели: без этого
    `bind_tools` можно было бы «потерять» и не заметить.
    """

    responses: list[Any] = Field(default_factory=list)
    calls: list[list[Any]] = Field(default_factory=list)
    bound_tools: list[Any] = Field(default_factory=list)

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def bind_tools(self, tools: Any, **kwargs: Any) -> Any:
        """Как у настоящих моделей: инструменты уходят в вызов через kwargs.

        Базовая реализация LangChain бросает NotImplementedError, поэтому этот
        двойник её переопределяет — иначе тест не отличил бы поддержку
        инструментов от её отсутствия.
        """
        return self.bind(tools=list(tools), **kwargs)

    def _next(self, messages: list[BaseMessage], kwargs: dict[str, Any]) -> AIMessage:
        self.calls.append(list(messages))
        self.bound_tools.append(kwargs.get("tools"))
        index = min(len(self.calls) - 1, len(self.responses) - 1)
        scripted = self.responses[index] if self.responses else ""
        if isinstance(scripted, AIMessage):
            return scripted
        return AIMessage(content="" if scripted is None else str(scripted))

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        return ChatResult(
            generations=[ChatGeneration(message=self._next(messages, kwargs))]
        )

    def _stream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any | None = None,
        **kwargs: Any,
    ) -> Iterator[ChatGenerationChunk]:
        yield from scripted_chunks(self._next(messages, kwargs))


def scripted_chunks(answer: AIMessage) -> Iterator[ChatGenerationChunk]:
    """Разбивает заданный ответ на порции так, как это делает сервер.

    Текст идёт по словам, аргументы инструмента — по несколько символов:
    склеивать фрагменты обязан вызывающий, а не модель.
    """
    if answer.tool_calls:
        for position, call in enumerate(answer.tool_calls):
            call_id = str(call.get("id") or f"call-{position}")
            args = call.get("args")
            serialized = (
                args if isinstance(args, str) else json.dumps(args, ensure_ascii=False)
            )
            for piece_index, piece in enumerate(_pieces(serialized)):
                yield ChatGenerationChunk(
                    message=AIMessageChunk(
                        content="",
                        tool_call_chunks=[
                            {
                                "name": str(call.get("name") or "") if piece_index == 0 else None,
                                "args": piece,
                                "id": call_id if piece_index == 0 else None,
                                "index": position,
                                "type": "tool_call_chunk",
                            }
                        ],
                    )
                )
        return
    for piece in str(answer.content).split(" "):
        yield ChatGenerationChunk(message=AIMessageChunk(content=piece + " "))


def _pieces(text: str, size: int = 7) -> list[str]:
    return [text[index : index + size] for index in range(0, len(text), size)] or [""]
