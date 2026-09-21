"""Оркестрация на LangChain: сборка индекса и цепочка ответа.

Индексация: `loaders` → секции (`documents.section_documents`) → чанки
(`RecursiveCharacterTextSplitter`) → `langchain-chroma`. Ответ: гибридный
ретривер (`retrieval.build_retriever`) → LCEL-цепочка `prompt | ChatOpenAI |
StrOutputParser` со стримингом токенов.

Порты остались прежними (`core/ports.py`): прикладной слой по-прежнему видит
`search`, `stream_answer`, `cited_sources` и не знает про LangChain.
"""
from __future__ import annotations

import json
import logging
import re
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from langchain_classic.retrievers import EnsembleRetriever
from langchain_core.documents import Document
from langchain_core.language_models import BaseChatModel
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate

from . import loaders, manifest
from .config import Settings
from .documents import section_documents, split_documents, with_scalar_metadata
from .embeddings import (
    build_embeddings,
    embedder_name,
    embedding_dim,
    explain_embedding_error,
)
from .errors import EngineUnavailable
from .llm import build_chat_model, chat_model_name
from .prompts import ANSWER_TEMPLATE, QUERY_EXPANSION_PROMPT, SYSTEM_PROMPT, format_context
from .retrieval import Hit, build_retriever
from .retrieval import search as run_search
from .vectorstore import all_documents, build_store, delete_by_source, open_store

log = logging.getLogger("ragkb")


@dataclass
class Answer:
    """Готовый ответ — для скриптов оценки, без потоковой отдачи."""

    question: str
    text: str
    hits: list[Hit]
    used_sources: list[dict[str, Any]] = field(default_factory=list)
    elapsed: float = 0.0
    llm_backend: str = ""
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "question": self.question,
            "answer": self.text,
            "sources": self.used_sources,
            "chunks": [hit.to_dict() for hit in self.hits],
            "elapsed_sec": round(self.elapsed, 2),
            "llm": self.llm_backend,
            "warnings": self.warnings,
        }


@dataclass
class IndexReport:
    files: int
    chunks: int
    skipped: list[tuple[str, str]]
    elapsed: float
    embedder: str
    store_backend: str = ""
    warnings: list[str] = field(default_factory=list)
    # Файлы, которые лежат в каталоге, но в корпус не приняты: их индексация
    # не касается. Показываем их вызывающему коду — иначе пропажа документов
    # из выдачи выглядела бы необъяснимой.
    excluded: list[str] = field(default_factory=list)


# --------------------------------------------------------------------- индексация


def build_index(
    cfg: Settings,
    *,
    docs_dir: str | Path | None = None,
    progress: Callable[[str], None] | None = None,
    allow: Callable[[str], bool] | None = None,
) -> IndexReport:
    """Полная переиндексация каталога документов.

    `allow` — предикат по имени файла относительно каталога корпуса:
    индексируются только те документы, которые приняты в корпус (реестр
    ведёт прикладной слой). Без предиката берётся всё, что нашлось.
    """
    started = time.time()
    say = progress or (lambda _msg: None)
    source = Path(docs_dir or cfg.docs_dir)

    files, excluded = _accepted_only(loaders.discover(source), source, allow)
    for path in excluded:
        say(f"  × вне корпуса, пропущен {path.name}")
    if not files:
        if excluded:
            raise ValueError(
                f"Ни один файл не принят в корпус: {len(excluded)} файл(ов) лежат "
                f"в каталоге {source} мимо интерфейса. Примите их на странице "
                f"«Документы» или загрузите документы через интерфейс."
            )
        raise FileNotFoundError(f"В каталоге {source} не найдено поддерживаемых файлов")

    say(f"Эмбеддинги: {embedder_name(cfg.embedding)}")
    # Модель проверяется до разбора корпуса: чтение и нарезка всех файлов —
    # самая долгая часть сборки, и недоступная Ollama или неоттянутая модель
    # иначе выяснились бы только на первом запросе векторов.
    embeddings = build_embeddings(cfg.embedding)

    sections: list[Document] = []
    skipped: list[tuple[str, str]] = []
    facts: dict[str, dict[str, Any]] = {}
    indexed_files = 0
    for path in files:
        try:
            loaded = loaders.load(path)
        except Exception as exc:
            skipped.append((str(path), str(exc)))
            say(f"  ! пропущен {path.name}: {exc}")
            continue
        if not loaded.blocks:
            skipped.append((str(path), "не удалось извлечь текст (возможно, скан без OCR)"))
            say(f"  ! пустой текст: {path.name}")
            continue
        facts[loaded.path] = manifest.file_facts(path, loaded.checksum)
        sections.extend(section_documents(loaded))
        indexed_files += 1
        say(f"  + {path.name}: {len(loaded.blocks)} блоков")

    if not sections:
        raise ValueError("После разбора не осталось текста — проверьте исходные файлы")

    chunks = [
        with_scalar_metadata(chunk) for chunk in split_documents(sections, cfg.chunking)
    ]
    if not chunks:
        raise ValueError("После нарезки не осталось текста — проверьте исходные файлы")
    say(f"Чанков получено: {len(chunks)}")

    store = build_store(cfg, embeddings)
    say(f"Хранилище: {cfg.store.backend}")
    try:
        store.add_documents(chunks, ids=[str(chunk.metadata["chunk_id"]) for chunk in chunks])
    except Exception as exc:
        raise EngineUnavailable(explain_embedding_error(exc, cfg.embedding)) from exc

    dim = embedding_dim(embeddings) or len(embeddings.embed_query("проверка"))
    manifest.write(
        cfg,
        store_backend=cfg.store.backend.lower(),
        embedder=embedder_name(cfg.embedding),
        dim=int(dim),
        chunks=len(chunks),
        documents=manifest.documents_summary(chunks, facts),
        skipped=skipped,
    )

    return IndexReport(
        files=indexed_files,
        chunks=len(chunks),
        skipped=skipped,
        elapsed=time.time() - started,
        embedder=embedder_name(cfg.embedding),
        store_backend=cfg.store.backend.lower(),
        excluded=[str(path) for path in excluded],
    )


def _accepted_only(
    files: list[Path], source: Path, allow: Callable[[str], bool] | None
) -> tuple[list[Path], list[Path]]:
    """Делит найденные файлы на принятые в корпус и оставшиеся в стороне."""
    if allow is None:
        return list(files), []
    accepted: list[Path] = []
    excluded: list[Path] = []
    for path in files:
        name = loaders.relative_name(path, source)
        (accepted if allow(name) else excluded).append(path)
    return accepted, excluded


# ------------------------------------------------------------------------ RAG


class RagChain:
    """Цепочка ответа на LangChain. Удовлетворяет порт AnswerEngine структурно."""

    def __init__(self, cfg: Settings):
        self.cfg = cfg
        # Нет манифеста — нет индекса: хранилище создало бы пустую коллекцию
        # и молча отвечало «ничего не найдено».
        indexed = manifest.read(cfg)
        self.embeddings = build_embeddings(cfg.embedding)
        self._check_indexed_with(indexed)
        self.store = open_store(cfg, self.embeddings)
        self.retriever = build_retriever(cfg, self.store)
        self.prompt = answer_prompt()
        self._llm: BaseChatModel | None = None

    def _check_indexed_with(self, indexed: dict[str, Any]) -> None:
        """Индекс обязан быть собран тем же эмбеддером и хранилищем.

        Иначе поиск вернул бы мусор: векторы другой модели несопоставимы,
        а чанки другого хранилища просто не найдутся.
        """
        wanted_embedder = embedder_name(self.cfg.embedding)
        indexed_embedder = str(indexed.get("embedder") or "")
        if indexed_embedder and indexed_embedder != wanted_embedder:
            raise ValueError(
                f"Индекс построен эмбеддером «{indexed_embedder}», а конфиг требует "
                f"«{wanted_embedder}». Переиндексируйте базу или верните прежнюю модель."
            )
        indexed_store = str(indexed.get("store") or "")
        if indexed_store and indexed_store != self.cfg.store.backend.lower():
            raise ValueError(
                f"Индекс построен хранилищем «{indexed_store}», а конфиг требует "
                f"«{self.cfg.store.backend}». Перестройте индекс на странице "
                f"«Документы» или верните прежнее хранилище."
            )
        expected_dim = int(indexed.get("dim") or 0)
        actual_dim = embedding_dim(self.embeddings)
        if expected_dim and actual_dim and expected_dim != actual_dim:
            raise ValueError(
                f"Индекс построен векторами длиной {expected_dim}, а эмбеддер "
                f"«{wanted_embedder}» выдаёт {actual_dim}. Переиндексируйте базу "
                f"или верните прежние параметры эмбеддинга."
            )

    # --------------------------------------------------------------- поиск

    def search(
        self, question: str, top_k: int | None = None, expand: bool = False
    ) -> list[Hit]:
        if not expand:
            return run_search(
                self.cfg, self.retriever, self.store, self.embeddings, question, top_k
            )
        queries = [question, *self._expand_query(question)]
        rankings = [
            run_search(
                self.cfg,
                self.retriever,
                self.store,
                self.embeddings,
                query,
                top_k or self.cfg.retrieval.candidates,
            )
            for query in queries
        ]
        return self._fuse_rankings(rankings, top_k)

    def _fuse_rankings(self, rankings: list[list[Hit]], top_k: int | None) -> list[Hit]:
        """Слияние выдач по перефразировкам — тем же RRF, что и внутри поиска."""
        lists = [[hit.document for hit in hits] for hits in rankings if hits]
        if not lists:
            return []
        # Список выдач на каждый вариант запроса — значит и «ретриверов»
        # в объекте слияния столько же: веса у LC должны совпадать по длине.
        fusion = EnsembleRetriever(
            retrievers=[self.retriever] * len(lists),
            weights=[1.0] * len(lists),
            c=self.cfg.retrieval.rrf_k,
            id_key="chunk_id",
        )
        fused = fusion.weighted_reciprocal_rank(lists)
        best: dict[str, Hit] = {}
        for hits in rankings:
            for hit in hits:
                keeper = best.get(hit.chunk_id)
                if keeper is None or hit.score > keeper.score:
                    best[hit.chunk_id] = hit
        out: list[Hit] = []
        for document in fused:
            found = best.get(str(document.metadata.get("chunk_id") or ""))
            if found is not None:
                out.append(found)
        return out[: (top_k or self.cfg.retrieval.top_k)]

    def _expand_query(self, question: str, n: int = 2) -> list[str]:
        prompt = QUERY_EXPANSION_PROMPT.format(n=n, question=question)
        try:
            answer = self._chat_model().invoke(
                [("system", "Ты помогаешь искать по базе документов."), ("human", prompt)]
            )
            raw = answer.text
        except Exception as exc:
            log.warning("расширение запроса не удалось (%s) — ищем по исходному вопросу", exc)
            return []
        return parse_expanded_queries(str(raw), question, n)

    # ---------------------------------------------------------------- ответ

    def stream_answer(
        self,
        question: str,
        *,
        top_k: int | None = None,
        expand: bool = False,
        model: str | None = None,
    ) -> tuple[list[Hit], Iterator[str]]:
        """Возвращает находки и поток токенов: источники нужны до конца ответа."""
        hits = self.search(question, top_k=top_k, expand=expand)
        tokens = self.answer_chain(model).stream(
            {"context": format_context(hits), "question": question}
        )
        return hits, tokens

    def answer_chain(self, model: str | None = None) -> Any:
        """LCEL-цепочка ответа: промпт → модель → текст."""
        return self.prompt | self._chat_model(model) | StrOutputParser()

    def ask(
        self,
        question: str,
        *,
        top_k: int | None = None,
        expand: bool = False,
        model: str | None = None,
    ) -> Answer:
        """Ответ целиком, без потока: так меряют качество скрипты оценки."""
        started = time.time()
        hits = self.search(question, top_k=top_k, expand=expand)
        text = self.answer_chain(model).invoke(
            {"context": format_context(hits), "question": question}
        )
        warnings: list[str] = []
        if not hits:
            warnings.append("Поиск не вернул ни одного релевантного фрагмента")
        used = self.cited_sources(str(text), hits)
        if not used and "нет информации" not in str(text).lower():
            warnings.append("Модель не проставила ссылки на источники — ответ стоит проверить")
        return Answer(
            question=question,
            text=str(text),
            hits=hits,
            used_sources=used,
            elapsed=time.time() - started,
            llm_backend=chat_model_name(self.cfg.llm, model),
            warnings=warnings,
        )

    def _chat_model(self, model: str | None = None) -> BaseChatModel:
        if model is None or model == self.cfg.llm.model:
            if self._llm is None:
                self._llm = build_chat_model(self.cfg.llm)
            return self._llm
        # Модель выбрана в интерфейсе: собираем под конкретный запрос,
        # объект дешёвый — это обёртка над настройками.
        return build_chat_model(self.cfg.llm, model)

    def cited_sources(self, text: str, hits: list[Hit]) -> list[dict[str, Any]]:
        """Источники, на которые модель действительно сослалась.

        Номера берутся из текста ответа: считать использованными все
        найденные фрагменты нельзя — тогда ссылки врут.
        """
        used: list[dict[str, Any]] = []
        seen: set[int] = set()
        for match in re.finditer(r"\[(\d+)\]", text):
            number = int(match.group(1))
            if number in seen or not 1 <= number <= len(hits):
                continue
            seen.add(number)
            hit = hits[number - 1]
            source = dict(hit.to_dict())
            source["n"] = number
            # Текст фрагмента нужен интерфейсу, чтобы показать источник
            # без повторного запроса к индексу.
            source["text"] = hit.text
            used.append(source)
        return used

    # -------------------------------------------------------------- сведения

    def llm_available(self, model: str | None = None) -> bool:
        """Готова ли генерация по конфигурации — без обращения к серверу.

        Проверка дешёвая: /api/v1/status дёргается часто, а живой список
        моделей и так отдаёт bootstrap.
        """
        return bool(self.cfg.llm.base_url and (model or self.cfg.llm.model))


def answer_prompt() -> ChatPromptTemplate:
    """Промпт RAG: системные правила + контекст с пронумерованными фрагментами."""
    return ChatPromptTemplate.from_messages(
        [("system", SYSTEM_PROMPT), ("human", ANSWER_TEMPLATE)]
    )


def remove_document(cfg: Settings, path: str | Path) -> int:
    """Удаляет документ из индекса по исходному пути. Возвращает число чанков."""
    embeddings = build_embeddings(cfg.embedding)
    store = open_store(cfg, embeddings)
    removed = delete_by_source(store, str(Path(path)))
    if not removed:
        return 0
    previous = manifest.read(cfg)
    remaining = all_documents(store)
    manifest.write(
        cfg,
        store_backend=cfg.store.backend.lower(),
        embedder=embedder_name(cfg.embedding),
        dim=int(previous.get("dim") or 0),
        chunks=len(remaining),
        documents=manifest.merged_documents(remaining, previous.get("documents")),
        skipped=previous.get("skipped"),
    )
    return removed


def parse_expanded_queries(raw: str, question: str, n: int) -> list[str]:
    """Достаёт перефразировки вопроса из ответа модели.

    Контракт — JSON `{"queries": [...]}`: он переживает и нумерацию, и
    вводные пояснения. Модели поменьше его нарушают, поэтому есть запасной
    разбор по строкам: одна кривая перефразировка полезнее, чем ни одной.
    Исходный вопрос и повторы отбрасываем — они уже есть в поиске.
    """
    queries = _queries_from_json(raw)
    if not queries:
        queries = [re.sub(r"^[\d\-.)\s]+", "", line).strip() for line in raw.splitlines()]
    out: list[str] = []
    seen = {_normalized(question)}
    for query in queries:
        candidate = " ".join(query.split())
        key = _normalized(candidate)
        if len(candidate) <= 5 or key in seen:
            continue
        seen.add(key)
        out.append(candidate)
        if len(out) >= n:
            break
    return out


def _queries_from_json(raw: str) -> list[str]:
    """Вырезает список перефразировок из ответа, если он похож на JSON."""
    start, end = raw.find("{"), raw.rfind("}")
    if start < 0 or end <= start:
        return []
    try:
        body = json.loads(raw[start : end + 1])
    except ValueError:
        return []
    if not isinstance(body, dict):
        return []
    values = body.get("queries") or body.get("questions") or []
    if not isinstance(values, list):
        return []
    return [value for value in values if isinstance(value, str)]


def _normalized(text: str) -> str:
    return " ".join(text.split()).casefold()
