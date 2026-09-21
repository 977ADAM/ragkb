"""Поиск на ретриверах LangChain: гибрид (плотный + BM25) через RRF, MMR, реранк.

Почему гибрид, а не только векторы: плотный поиск хорошо ловит перефразировки
(«как отпроситься» → «предоставление отпуска»), но проваливается на точных
сущностях — артикулах, номерах приказов, аббревиатурах. BM25 наоборот. Их
объединение даёт заметно более устойчивый recall, чем любой из двух отдельно.

Слияние — Reciprocal Rank Fusion из `langchain-classic.EnsembleRetriever`:
складываются не сырые оценки (BM25 выдаёт 0…30, косинус 0…1 — складывать
нельзя), а обратные ранги. Лексическая половина — свой `LexicalRetriever`
на `rank_bm25` (пакет `langchain-community` объявлен устаревшим, поэтому
зависимость от него не тянем), с русской токенизацией из `core.text`.

Оценка в выдаче — близость плотного поиска: именно на неё смотрит порог
`retrieval.min_score`. Порядок задаёт RRF, поэтому score не обязан убывать.
"""
from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

import httpx
import numpy as np
from langchain_classic.retrievers import ContextualCompressionRetriever, EnsembleRetriever
from langchain_core.callbacks import CallbackManagerForRetrieverRun
from langchain_core.documents import Document
from langchain_core.documents.compressor import BaseDocumentCompressor
from langchain_core.embeddings import Embeddings
from langchain_core.retrievers import BaseRetriever
from langchain_core.vectorstores import VectorStore

from .config import Settings
from .documents import document_citation, document_page, document_section, document_text
from .errors import EngineUnavailable
from .text import tokenize
from .vectorstore import all_documents, vectors_for

log = logging.getLogger("ragkb")

_RERANK_PREFIX = "relevance_score"


@dataclass
class Hit:
    """Находка поиска: документ LangChain и то, чем он подтверждён."""

    document: Document
    score: float
    dense_score: float | None = None
    lexical_score: float | None = None
    rerank_score: float | None = None
    rank_sources: list[str] = field(default_factory=list)

    @property
    def chunk_id(self) -> str:
        return str(self.document.metadata.get("chunk_id") or "")

    @property
    def text(self) -> str:
        return document_text(self.document)

    @property
    def citation(self) -> str:
        return document_citation(self.document)

    def to_dict(self) -> dict[str, Any]:
        """Форма для /api/v1/search и для сносок в ответе."""
        return {
            "chunk_id": self.chunk_id,
            "text": self.text,
            "citation": self.citation,
            "source": str(self.document.metadata.get("source") or ""),
            "page": document_page(self.document),
            "section": document_section(self.document),
            "score": round(self.score, 4),
            "dense_score": None if self.dense_score is None else round(self.dense_score, 4),
            "lexical_score": (
                None if self.lexical_score is None else round(self.lexical_score, 4)
            ),
            "rerank_score": (
                None if self.rerank_score is None else round(self.rerank_score, 4)
            ),
            "matched_by": self.rank_sources,
        }


# ------------------------------------------------------------ лексический поиск


class LexicalRetriever(BaseRetriever):
    """BM25 по документам индекса: лексическая половина гибрида.

    Свой ретривер вместо `langchain_community.retrievers.BM25Retriever`:
    community объявлен устаревшим, а нам нужны русская токенизация
    (`core.text.tokenize`) и оценка BM25 в метаданных находки.
    """

    documents: list[Document]
    k: int = 30
    preprocess: Callable[[str], list[str]] = tokenize
    _bm25: Any = None

    def model_post_init(self, __context: Any) -> None:
        from rank_bm25 import BM25Okapi

        corpus = [self.preprocess(document.page_content) for document in self.documents]
        self._bm25 = BM25Okapi(corpus) if corpus else None

    def _get_relevant_documents(
        self, query: str, *, run_manager: CallbackManagerForRetrieverRun | None = None
    ) -> list[Document]:
        if self._bm25 is None:
            return []
        tokens = self.preprocess(query)
        if not tokens:
            return []
        scores = self._bm25.get_scores(tokens)
        ranked = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)
        out: list[Document] = []
        for index in ranked[: self.k]:
            score = float(scores[index])
            if score <= 0:
                # BM25 без совпадений даёт нули: такие документы не находки.
                break
            document = self.documents[index]
            document.metadata["lexical_score"] = score
            out.append(document)
        return out


# ------------------------------------------------------------------- сборка


def build_retriever(cfg: Settings, store: VectorStore) -> BaseRetriever:
    """Ретривер по конфигурации: плотный, лексический, их слияние и реранк."""
    retrieval = cfg.retrieval
    legs: list[BaseRetriever] = []
    weights: list[float] = []

    if retrieval.use_dense:
        legs.append(dense_retriever(store, retrieval))
        weights.append(retrieval.dense_weight)
    if retrieval.use_bm25:
        legs.append(
            LexicalRetriever(
                documents=all_documents(store),
                k=max(retrieval.candidates, retrieval.top_k),
            )
        )
        weights.append(retrieval.bm25_weight)
    if not legs:
        raise EngineUnavailable(
            "Оба поиска выключены (retrieval.use_dense и retrieval.use_bm25): "
            "отвечать по базе нечем"
        )

    base: BaseRetriever = (
        legs[0]
        if len(legs) == 1
        else EnsembleRetriever(
            retrievers=legs,  # type: ignore[arg-type]
            weights=weights,
            c=retrieval.rrf_k,
            id_key="chunk_id",
        )
    )
    if retrieval.reranker == "http":
        return ContextualCompressionRetriever(
            base_compressor=HttpReranker(
                url=retrieval.reranker_url,
                model=retrieval.reranker_model,
                api_key=retrieval.reranker_api_key,
                timeout=retrieval.reranker_timeout,
            ),
            base_retriever=base,
        )
    return base


def dense_retriever(store: VectorStore, retrieval: Settings.RetrievalConfig) -> BaseRetriever:
    """Плотная половина: MMR или обычная близость."""
    if retrieval.use_mmr:
        # fetch_k больше k: MMR нужно из чего выбирать разнообразие.
        return store.as_retriever(
            search_type="mmr",
            search_kwargs={
                "k": retrieval.candidates,
                "fetch_k": max(retrieval.candidates * 3, retrieval.top_k),
                "lambda_mult": retrieval.mmr_lambda,
            },
        )
    return store.as_retriever(search_kwargs={"k": retrieval.candidates})


def search(
    cfg: Settings,
    retriever: BaseRetriever,
    store: VectorStore,
    embeddings: Embeddings,
    question: str,
    top_k: int | None = None,
) -> list[Hit]:
    """Поиск с оценками и порогами — то, что видит прикладной слой."""
    retrieval = cfg.retrieval
    limit = top_k or retrieval.top_k
    documents = retriever.invoke(question)
    scores = dense_scores(store, embeddings, question, documents)
    hits: list[Hit] = []
    for document in documents:
        chunk_id = str(document.metadata.get("chunk_id") or "")
        dense = scores.get(chunk_id)
        lexical = document.metadata.get("lexical_score")
        rerank = document.metadata.get(_RERANK_PREFIX)
        hits.append(
            Hit(
                document=document,
                score=_final_score(dense, rerank),
                dense_score=dense,
                lexical_score=float(lexical) if isinstance(lexical, (int, float)) else None,
                rerank_score=float(rerank) if isinstance(rerank, (int, float)) else None,
                rank_sources=_sources(document, dense, lexical),
            )
        )

    if retrieval.min_score > 0:
        hits = [
            hit
            for hit in hits
            if hit.dense_score is None or hit.dense_score >= retrieval.min_score
        ]
    if retrieval.min_rerank_score > 0:
        threshold = retrieval.min_rerank_score
        scored = [
            hit
            for hit in hits
            if hit.rerank_score is not None and hit.rerank_score >= threshold
        ]
        # Если реранкер не отработал, оценок нет и отсекать нечего: пустая
        # выдача здесь означала бы «нет информации» на ровном месте.
        hits = scored or [hit for hit in hits if hit.rerank_score is None]
    return hits[:limit]


def dense_scores(
    store: VectorStore, embeddings: Embeddings, question: str, documents: Sequence[Document]
) -> dict[str, float]:
    """Близость плотного поиска для найденных чанков.

    Нужна для порога `min_score` и для оценки в выдаче: слияние RRF отдаёт
    порядок, но не близость. Считаем одним запросом к хранилищу; если
    документ в него не попал — оценки нет, и порог его не отсекает.
    """
    if not documents:
        return {}
    wanted = [str(document.metadata.get("chunk_id") or "") for document in documents]
    try:
        found = store.similarity_search_with_relevance_scores(question, k=len(documents))
    except Exception:
        # Хранилище в памяти не умеет relevance score (NotImplementedError) —
        # считаем косинус по сохранённым векторам.
        return _cosine_scores(store, embeddings, question, wanted)
    return {
        str(document.metadata.get("chunk_id") or ""): float(score)
        for document, score in found
        if str(document.metadata.get("chunk_id") or "") in wanted
    }


def _cosine_scores(
    store: VectorStore, embeddings: Embeddings, question: str, chunk_ids: list[str]
) -> dict[str, float]:
    vectors = vectors_for(store, chunk_ids)
    if not vectors:
        return {}
    query = np.asarray(embeddings.embed_query(question), dtype=np.float32)
    query_norm = float(np.linalg.norm(query)) or 1.0
    out: dict[str, float] = {}
    for chunk_id in chunk_ids:
        vector = vectors.get(chunk_id)
        if vector is None:
            continue
        values = np.asarray(vector, dtype=np.float32)
        norm = float(np.linalg.norm(values)) or 1.0
        out[chunk_id] = float(query @ values / (query_norm * norm))
    return out


def _final_score(dense: float | None, rerank: Any) -> float:
    if isinstance(rerank, (int, float)):
        return float(rerank)
    return float(dense) if dense is not None else 0.0


def _sources(document: Document, dense: float | None, lexical: Any) -> list[str]:
    """Чем подтверждена находка — для разбора качества поиска."""
    out: list[str] = []
    if dense is not None:
        out.append("dense")
    if isinstance(lexical, (int, float)):
        out.append("lexical")
    if document.metadata.get(_RERANK_PREFIX) is not None:
        out.append("rerank")
    return out


# ------------------------------------------------------------------ реранкер


class HttpReranker(BaseDocumentCompressor):
    """Реранкер по HTTP: POST {query, documents} → оценки по индексам.

    Формат запроса и ответа совпадает у Jina, Cohere и совместимых сервисов,
    поэтому отдельная библиотека не нужна: нужен один запрос и разбор ответа.
    Локальный cross-encoder не поддерживаем: он требует torch в процессе.
    """

    url: str = ""
    model: str = ""
    api_key: str = ""
    timeout: int = 60

    def compress_documents(
        self,
        documents: Sequence[Document],
        query: str,
        callbacks: Any | None = None,
    ) -> list[Document]:
        if not documents:
            return []
        if not self.url:
            log.warning(
                "retrieval.reranker: http, но retrieval.reranker_url не задан — "
                "реранк пропущен, порядок остался после RRF"
            )
            return list(documents)
        try:
            scores = _rerank_scores(
                url=self.url,
                model=self.model,
                api_key=self.api_key,
                timeout=self.timeout,
                query=query,
                documents=[document.page_content for document in documents],
            )
        except Exception as exc:
            log.warning("внешний реранкер недоступен (%s) — порядок оставлен как есть", exc)
            return list(documents)
        if not scores:
            return list(documents)
        ranked: list[Document] = []
        for document, score in zip(documents, scores, strict=False):
            document.metadata[_RERANK_PREFIX] = float(score)
            ranked.append(document)
        return sorted(
            ranked, key=lambda doc: float(doc.metadata[_RERANK_PREFIX]), reverse=True
        )


def _rerank_scores(
    *,
    url: str,
    model: str,
    api_key: str,
    timeout: int,
    query: str,
    documents: list[str],
) -> list[float]:
    payload: dict[str, Any] = {"query": query, "documents": documents, "top_n": len(documents)}
    if model:
        payload["model"] = model
    headers = {"content-type": "application/json"}
    if api_key:
        headers["authorization"] = f"Bearer {api_key}"
    response = httpx.post(rerank_endpoint(url), json=payload, headers=headers, timeout=timeout)
    response.raise_for_status()
    return parse_rerank_scores(response.json(), len(documents))


def rerank_endpoint(url: str) -> str:
    """Дополняет адрес до конечной точки реранка.

    Принимаем и корень OpenAI-совместимого API (`http://host:8000/v1`), и
    полный адрес: оператору привычнее указать базу — так же, как для LLM.
    """
    cleaned = url.strip().rstrip("/")
    if cleaned.endswith("/rerank"):
        return cleaned
    return f"{cleaned}/rerank"


def parse_rerank_scores(body: Any, count: int) -> list[float]:
    """Разбирает ответ реранкера: [{"index": i, "relevance_score": s}, …].

    Индекс приходит явно, поэтому порядок элементов в ответе не важен.
    Неоценённые документы получают минимальную оценку: иначе они всплывут
    наверху и вытеснят те, которые модель действительно проверила.
    Пустой результат означает «реранкер не ответил по существу» — вызывающий
    код в этом случае оставляет прежний порядок.
    """
    if not isinstance(body, dict):
        return []
    items = body.get("results") or body.get("data") or []
    if not isinstance(items, list):
        return []
    scores: dict[int, float] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        index = item.get("index")
        value = item.get("relevance_score", item.get("score"))
        if not isinstance(index, int) or not 0 <= index < count or value is None:
            continue
        try:
            scores[index] = float(value)
        except (TypeError, ValueError):
            continue
    if not scores:
        return []
    floor = min(scores.values())
    return [scores.get(i, floor) for i in range(count)]
