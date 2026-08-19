"""Оркестрация: индексация и вопрос-ответ."""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterator

import numpy as np

from . import loaders
from .chunking import Chunk, chunk_documents
from .config import Config
from .embeddings import Embedder, TfidfEmbedder, build_embedder  # noqa: F401
from .llm import LLM, LLMError, build_llm
from .prompts import (
    ANSWER_TEMPLATE,
    CONDENSE_PROMPT,
    QUERY_EXPANSION_PROMPT,
    SYSTEM_PROMPT,
    format_context,
)
from .retrieval import Hit, Retriever, reciprocal_rank_fusion
from .store import BaseStore, create_store, open_store


@dataclass
class Answer:
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
            "chunks": [h.to_dict() for h in self.hits],
            "elapsed_sec": round(self.elapsed, 2),
            "llm": self.llm_backend,
            "warnings": self.warnings,
        }


# --------------------------------------------------------------------- индексация

@dataclass
class IndexReport:
    files: int
    chunks: int
    skipped: list[tuple[str, str]]
    elapsed: float
    embedder: str
    store_backend: str = ""
    warnings: list[str] = field(default_factory=list)


def build_index(
    cfg: Config,
    *,
    docs_dir: str | Path | None = None,
    progress: Callable[[str], None] | None = None,
) -> IndexReport:
    """Полная переиндексация каталога документов."""
    started = time.time()
    say = progress or (lambda _msg: None)
    source = Path(docs_dir or cfg.docs_dir)

    files = loaders.discover(source)
    if not files:
        raise FileNotFoundError(f"В каталоге {source} не найдено поддерживаемых файлов")

    documents = []
    skipped: list[tuple[str, str]] = []
    for path in files:
        try:
            doc = loaders.load(path)
        except Exception as exc:
            skipped.append((str(path), str(exc)))
            say(f"  ! пропущен {path.name}: {exc}")
            continue
        if not doc.blocks:
            skipped.append((str(path), "не удалось извлечь текст (возможно, скан без OCR)"))
            say(f"  ! пустой текст: {path.name}")
            continue
        documents.append(doc)
        say(f"  + {path.name}: {len(doc.blocks)} блоков")

    chunks = chunk_documents(documents, cfg.chunking)
    if not chunks:
        raise ValueError("После чанкинга не осталось текста — проверьте исходные файлы")
    say(f"Чанков получено: {len(chunks)}")

    embedder = build_embedder(cfg.embedding)
    say(f"Эмбеддинги: {embedder.name}")
    vectors = embedder.embed_documents([c.embed_text for c in chunks])

    store = create_store(cfg)
    say(f"Хранилище: {store.backend_name}")
    store.build(
        chunks,
        vectors,
        embedder_name=embedder.name,
        embedder_state=embedder.state(),
        extra={
            "chunk_size": cfg.chunking.size,
            "chunk_overlap": cfg.chunking.overlap,
            "skipped": skipped,
        },
    )
    store.save()

    return IndexReport(
        files=len(documents),
        chunks=len(chunks),
        skipped=skipped,
        elapsed=time.time() - started,
        embedder=embedder.name,
        store_backend=store.backend_name,
    )


def update_documents(
    cfg: Config,
    paths: list[str | Path],
    *,
    progress: Callable[[str], None] | None = None,
) -> IndexReport:
    """Добавляет или обновляет отдельные документы без полной переиндексации.

    Работает только на бэкенде chroma: у него есть upsert и delete по id.
    numpy-хранилище держит одну матрицу целиком, и точечная правка в нём
    означала бы перезапись всего файла — проще пересобрать индекс.
    """
    from .store import ChromaStore

    started = time.time()
    say = progress or (lambda _msg: None)

    store = open_store(cfg)
    if not isinstance(store, ChromaStore):
        raise ValueError(
            "Инкрементальное обновление доступно только при store.backend: chroma. "
            "Для numpy выполните полную переиндексацию: ragkb index --rebuild"
        )

    embedder = build_embedder(cfg.embedding)
    if store.embedder_state:
        embedder.load_state(store.embedder_state)

    warnings: list[str] = []
    if isinstance(embedder, TfidfEmbedder):
        # Словарь IDF заморожен на момент полной индексации: слова, которых не
        # было в корпусе, получают нейтральный вес, и новые документы хуже
        # находятся плотным поиском. У нейросетевых эмбеддеров этого нет.
        warnings.append(
            "Эмбеддер TF-IDF: словарь IDF не обновляется при инкрементальной "
            "загрузке — новые термины получат нейтральный вес. Периодически "
            "выполняйте полную переиндексацию или используйте backend: ollama."
        )

    total_chunks = 0
    skipped: list[tuple[str, str]] = []
    for path in paths:
        for file_path in loaders.discover(path):
            try:
                doc = loaders.load(file_path)
            except Exception as exc:
                skipped.append((str(file_path), str(exc)))
                continue
            chunks = chunk_documents([doc], cfg.chunking)
            if not chunks:
                skipped.append((str(file_path), "пустой текст"))
                continue
            vectors = embedder.embed_documents([c.embed_text for c in chunks])
            store.upsert_document(chunks, vectors)
            total_chunks += len(chunks)
            say(f"  ~ {file_path.name}: {len(chunks)} чанков обновлено")

    store.save()
    return IndexReport(
        files=len(paths),
        chunks=total_chunks,
        skipped=skipped,
        elapsed=time.time() - started,
        embedder=embedder.name,
        store_backend=store.backend_name,
        warnings=warnings,
    )


def remove_document(cfg: Config, path: str | Path) -> int:
    """Удаляет документ из индекса по исходному пути. Возвращает число чанков."""
    from .store import ChromaStore

    store = open_store(cfg)
    if not isinstance(store, ChromaStore):
        raise ValueError("Удаление доступно только при store.backend: chroma")
    target = str(Path(path))
    doc_ids = {c.doc_id for c in store.chunks if c.source == target or Path(c.source).name == Path(target).name}
    removed = sum(store.delete_document(doc_id) for doc_id in doc_ids)
    store.save()
    return removed


# ------------------------------------------------------------------------ RAG

class RAGPipeline:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.store: BaseStore = open_store(cfg)
        self.embedder = self._restore_embedder()
        self.retriever = Retriever(self.store, self.embedder, cfg.retrieval)
        self.llm: LLM = build_llm(cfg.llm)

    def _restore_embedder(self) -> Embedder:
        """Эмбеддер запроса обязан совпадать с тем, чем строился индекс."""
        indexed_with = self.store.manifest.get("embedder", "")
        embedder = build_embedder(self.cfg.embedding)
        if indexed_with and embedder.name != indexed_with:
            raise ValueError(
                f"Индекс построен эмбеддером «{indexed_with}», а конфиг требует "
                f"«{embedder.name}». Переиндексируйте базу или верните прежнюю модель."
            )
        state = self.store.embedder_state
        if state:
            embedder.load_state(state)
        return embedder

    # --------------------------------------------------------------- поиск

    def search(self, question: str, top_k: int | None = None, expand: bool = False) -> list[Hit]:
        if not expand:
            return self.retriever.search(question, top_k)
        queries = [question, *self._expand_query(question)]
        rankings: dict[str, list[tuple[str, float]]] = {}
        pool: dict[str, Hit] = {}
        for i, query in enumerate(queries):
            hits = self.retriever.search(query, top_k=self.cfg.retrieval.candidates)
            rankings[f"q{i}"] = [(h.chunk.chunk_id, h.score) for h in hits]
            for hit in hits:
                pool.setdefault(hit.chunk.chunk_id, hit)
        fused = reciprocal_rank_fusion(rankings, k=self.cfg.retrieval.rrf_k)
        result = []
        for chunk_id, score, _sources in fused[: (top_k or self.cfg.retrieval.top_k)]:
            hit = pool[chunk_id]
            hit.score = score
            result.append(hit)
        return result

    def _expand_query(self, question: str, n: int = 2) -> list[str]:
        try:
            raw = self.llm.generate(
                "Ты помогаешь искать по базе документов.",
                QUERY_EXPANSION_PROMPT.format(n=n, question=question),
            )
        except (LLMError, Exception):
            return []
        lines = [re.sub(r"^[\d\-\.\)\s]+", "", ln).strip() for ln in raw.splitlines()]
        return [ln for ln in lines if len(ln) > 5][:n]

    # ---------------------------------------------------------------- ответ

    def ask(
        self,
        question: str,
        *,
        top_k: int | None = None,
        history: list[tuple[str, str]] | None = None,
        expand: bool = False,
    ) -> Answer:
        started = time.time()
        warnings: list[str] = []

        search_query = question
        if history:
            search_query = self._condense(question, history) or question

        hits = self.search(search_query, top_k=top_k, expand=expand)
        if not hits:
            return Answer(
                question=question,
                text="В базе знаний нет информации по этому вопросу.",
                hits=[],
                elapsed=time.time() - started,
                llm_backend=self.llm.name,
                warnings=["Поиск не вернул ни одного релевантного фрагмента"],
            )

        context = format_context(hits)
        prompt = ANSWER_TEMPLATE.format(context=context, question=question)
        try:
            text = self.llm.generate(SYSTEM_PROMPT, prompt)
        except LLMError as exc:
            warnings.append(f"{exc} — ответ собран экстрактивно")
            from .llm import ExtractiveLLM

            text = ExtractiveLLM(self.cfg.llm).generate(SYSTEM_PROMPT, prompt)

        used = self._cited_sources(text, hits)
        if not used and "нет информации" not in text.lower():
            warnings.append("Модель не проставила ссылки на источники — ответ стоит проверить")

        return Answer(
            question=question,
            text=text,
            hits=hits,
            used_sources=used,
            elapsed=time.time() - started,
            llm_backend=self.llm.name,
            warnings=warnings,
        )

    def stream_answer(self, question: str, top_k: int | None = None) -> Iterator[str]:
        hits = self.search(question, top_k=top_k)
        if not hits:
            yield "В базе знаний нет информации по этому вопросу."
            return
        prompt = ANSWER_TEMPLATE.format(context=format_context(hits), question=question)
        yield from self.llm.stream(SYSTEM_PROMPT, prompt)

    # ------------------------------------------------------------ служебное

    def _condense(self, question: str, history: list[tuple[str, str]]) -> str | None:
        window = self.cfg.history.window
        recent = history[-window:] if window > 0 else []
        formatted = "\n".join(f"Пользователь: {q}\nАссистент: {a}" for q, a in recent)
        try:
            return self.llm.generate(
                "Ты переформулируешь вопросы.",
                CONDENSE_PROMPT.format(history=formatted, question=question),
            ).strip()
        except Exception:
            return None

    @staticmethod
    def _cited_sources(text: str, hits: list[Hit]) -> list[dict[str, Any]]:
        """Собирает список реально процитированных источников по маркерам [N]."""
        numbers = {int(n) for n in re.findall(r"\[(\d+)\]", text)}
        out = []
        for i, hit in enumerate(hits, start=1):
            if i in numbers:
                out.append(
                    {
                        "n": i,
                        "citation": hit.chunk.citation(),
                        "source": hit.chunk.source,
                        "page": hit.chunk.page,
                        "score": round(hit.score, 4),
                    }
                )
        return out

    def stats(self) -> dict[str, Any]:
        return {
            "chunks": len(self.store),
            "documents": len(self.store.manifest.get("documents", [])),
            "store": self.store.backend_name,
            "embedder": self.store.manifest.get("embedder"),
            "llm": self.llm.name,
            "llm_available": self.llm.available(),
            "index_dir": str(self.store.dir),
        }
