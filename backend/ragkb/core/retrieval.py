"""Гибридный поиск: BM25 + плотные векторы, слияние RRF, MMR, опциональный реранк.

Почему гибрид, а не только векторы: плотный поиск хорошо ловит перефразировки
(«как отпроситься» → «предоставление отпуска»), но проваливается на точных
сущностях — артикулах, номерах приказов, аббревиатурах. BM25 наоборот. Их
объединение даёт заметно более устойчивый recall, чем любой из двух отдельно.

Слияние — Reciprocal Rank Fusion: складываются не сырые оценки (они в разных
шкалах и несопоставимы), а обратные ранги. Это делает схему устойчивой к тому,
что BM25 выдаёт значения 0..30, а косинус 0..1.

Вес источника в слиянии настраивается (`retrieval.bm25_weight`/`dense_weight`):
когда по замерам один из поисков явно полезнее, его вклад можно усилить,
не трогая шкалы оценок.
"""
from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from typing import Any

import httpx
import numpy as np

from .chunking import Chunk
from .config import Settings
from .embeddings import Embedder
from .store import BaseStore

log = logging.getLogger("ragkb")


@dataclass
class Hit:
    chunk: Chunk
    score: float                       # итоговая оценка после слияния
    dense_score: float | None = None
    lexical_score: float | None = None
    rerank_score: float | None = None
    rank_sources: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "chunk_id": self.chunk.chunk_id,
            "text": self.chunk.text,
            "citation": self.chunk.citation(),
            "source": self.chunk.source,
            "page": self.chunk.page,
            "section": self.chunk.section,
            "score": round(self.score, 4),
            "dense_score": None if self.dense_score is None else round(self.dense_score, 4),
            "lexical_score": None if self.lexical_score is None else round(self.lexical_score, 4),
            "rerank_score": None if self.rerank_score is None else round(self.rerank_score, 4),
            "matched_by": self.rank_sources,
        }


class Retriever:
    def __init__(self, store: BaseStore, embedder: Embedder, cfg: Settings.RetrievalConfig):
        self.store = store
        self.embedder = embedder
        self.cfg = cfg
        self._reranker: Any = None

    def search(self, query: str, top_k: int | None = None) -> list[Hit]:
        top_k = top_k or self.cfg.top_k
        n_candidates = max(self.cfg.candidates, top_k)

        dense: list[tuple[str, float]] = []
        lexical: list[tuple[str, float]] = []
        query_vec: np.ndarray | None = None

        if self.cfg.use_dense and len(self.store):
            query_vec = self.embedder.embed_query(query)
            dense = self.store.dense_search(query_vec, n_candidates)
        if self.cfg.use_bm25:
            lexical = self.store.lexical_search(query, n_candidates)

        fused = reciprocal_rank_fusion(
            {"dense": dense, "lexical": lexical},
            k=self.cfg.rrf_k,
            weights={"dense": self.cfg.dense_weight, "lexical": self.cfg.bm25_weight},
        )
        if not fused:
            return []

        dense_map = dict(dense)
        lexical_map = dict(lexical)
        hits = [
            Hit(
                chunk=self.store.get_chunk(chunk_id),
                score=score,
                dense_score=dense_map.get(chunk_id),
                lexical_score=lexical_map.get(chunk_id),
                rank_sources=sources,
            )
            for chunk_id, score, sources in fused[:n_candidates]
        ]

        # Один и тот же абзац из двух файлов — это одна находка, а не две:
        # иначе он занимает позиции в top-k и вытесняет альтернативы.
        if self.cfg.dedupe_text:
            hits = collapse_duplicate_text(hits)

        # Отсечка по плотной близости: если ничего похожего нет, лучше честно
        # сказать «не найдено», чем скормить LLM случайные абзацы.
        if self.cfg.min_score > 0:
            hits = [
                h for h in hits
                if h.dense_score is None or h.dense_score >= self.cfg.min_score
            ]
            if not hits:
                return []

        if self.cfg.reranker != "none":
            hits = self._rerank(query, hits)
            hits = drop_below_rerank_score(hits, self.cfg.min_rerank_score)
            if not hits:
                return []

        if self.cfg.use_mmr and query_vec is not None and self.cfg.reranker == "none":
            hits = self._mmr(hits, query_vec, top_k)

        return hits[:top_k]

    # ------------------------------------------------------------------- MMR

    def _mmr(self, hits: list[Hit], query_vec: np.ndarray, top_k: int) -> list[Hit]:
        """Maximal Marginal Relevance — убирает почти одинаковые чанки из выдачи.

        Без него top-5 часто оказывается пятью вариациями одного абзаца из разных
        версий документа, и LLM не видит альтернативных формулировок.
        """
        if len(hits) <= 1:
            return hits
        vecs = self.store.get_vectors([h.chunk.chunk_id for h in hits])
        relevance = vecs @ query_vec

        selected: list[int] = []
        remaining = list(range(len(hits)))
        lam = self.cfg.mmr_lambda
        while remaining and len(selected) < top_k:
            if not selected:
                best = int(np.argmax(relevance[remaining]))
                selected.append(remaining.pop(best))
                continue
            sim_to_selected = vecs[remaining] @ vecs[selected].T
            penalty = sim_to_selected.max(axis=1)
            mmr_scores = lam * relevance[remaining] - (1 - lam) * penalty
            best = int(np.argmax(mmr_scores))
            selected.append(remaining.pop(best))
        return [hits[i] for i in selected]

    # --------------------------------------------------------------- реранкер

    def _rerank(self, query: str, hits: list[Hit]) -> list[Hit]:
        """Переставляет кандидатов по оценке реранкера.

        Локальный cross-encoder считает пару (запрос, чанк) целиком и точнее
        bi-encoder'а, но требует torch в процессе. Если в контуре уже есть
        отдельный сервис реранка (vLLM, TEI, Jina-совместимый шлюз), дешевле
        спросить его по HTTP и не тащить модель в контейнер rag.
        """
        if self.cfg.reranker == "http":
            scores = self._rerank_http(query, hits)
        else:
            scores = self._rerank_cross_encoder(query, hits)
        if scores is None:
            return hits
        for hit, score in zip(hits, scores, strict=False):
            hit.rerank_score = float(score)
            hit.score = float(score)
        return sorted(
            hits,
            key=lambda h: h.rerank_score if h.rerank_score is not None else 0.0,
            reverse=True,
        )

    def _rerank_cross_encoder(self, query: str, hits: list[Hit]) -> list[float] | None:
        if self._reranker is None:
            try:
                from sentence_transformers import CrossEncoder
                self._reranker = CrossEncoder(self.cfg.reranker_model)
            except ImportError:
                log.warning(
                    "реранкер %s не установлен: pip install 'ragkb[local-models]' "
                    "или переключитесь на retrieval.reranker: http",
                    self.cfg.reranker_model,
                )
                return None
        pairs = [(query, h.chunk.embed_text) for h in hits]
        try:
            return [float(s) for s in self._reranker.predict(pairs)]
        except Exception as exc:
            log.warning("локальный реранкер не отработал (%s) — порядок оставлен как есть", exc)
            return None

    def _rerank_http(self, query: str, hits: list[Hit]) -> list[float] | None:
        if not self.cfg.reranker_url:
            log.warning(
                "retrieval.reranker: http, но retrieval.reranker_url не задан — "
                "реранк пропущен, порядок остался после RRF"
            )
            return None
        reranker = _HttpReranker(
            url=self.cfg.reranker_url,
            model=self.cfg.reranker_model,
            api_key=self.cfg.reranker_api_key,
            timeout=self.cfg.reranker_timeout,
        )
        try:
            return reranker.rank(query, [h.chunk.embed_text for h in hits])
        except Exception as exc:
            log.warning("внешний реранкер недоступен (%s) — порядок оставлен как есть", exc)
            return None


class _HttpReranker:
    """Реранкер по HTTP: POST {query, documents} → оценки по индексам.

    Формат запроса и ответа совпадает у Jina, Cohere и совместимых сервисов,
    поэтому отдельная библиотека не нужна: нужен один запрос и разбор ответа.
    """

    def __init__(self, url: str, model: str = "", api_key: str = "", timeout: int = 60):
        self.url = rerank_endpoint(url)
        self.model = model
        self.api_key = api_key
        self.timeout = timeout

    def rank(self, query: str, documents: list[str]) -> list[float]:
        if not documents:
            return []
        payload: dict[str, Any] = {
            "query": query,
            "documents": documents,
            "top_n": len(documents),
        }
        if self.model:
            payload["model"] = self.model
        headers = {"content-type": "application/json"}
        if self.api_key:
            headers["authorization"] = f"Bearer {self.api_key}"
        response = httpx.post(
            self.url, json=payload, headers=headers, timeout=self.timeout
        )
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
    наверх и вытеснят те, которые модель действительно проверила.
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


def collapse_duplicate_text(hits: list[Hit]) -> list[Hit]:
    """Убирает из выдачи чанки с одинаковым текстом.

    Одинаковый абзац попадает в индекс дважды, когда документ лежит в двух
    файлах или переписан под новым именем: в top-k он занимает две позиции и
    вытесняет альтернативы. Оставляем первый — он выше по скору слияния, —
    а признаки находки сливаем: иначе потеряется то, что фрагмент подтверждён
    и лексическим, и плотным поиском.
    """
    seen: dict[str, Hit] = {}
    out: list[Hit] = []
    for hit in hits:
        key = _content_hash(hit.chunk.text)
        keeper = seen.get(key)
        if keeper is None:
            seen[key] = hit
            out.append(hit)
            continue
        for name in hit.rank_sources:
            if name not in keeper.rank_sources:
                keeper.rank_sources.append(name)
        if keeper.dense_score is None:
            keeper.dense_score = hit.dense_score
        if keeper.lexical_score is None:
            keeper.lexical_score = hit.lexical_score
    return out


def drop_below_rerank_score(hits: list[Hit], min_score: float) -> list[Hit]:
    """Отсекает кандидатов с низкой оценкой реранкера.

    Оценки реранкера безразмерны — у каждой модели своя шкала, поэтому порог
    задаётся конфигом и по умолчанию выключен. Если реранкер не отработал,
    оценки пусты и отсекать нечего: пустая выдача здесь означала бы «нет
    информации» на ровном месте.
    """
    if min_score <= 0:
        return hits
    scored = [h for h in hits if h.rerank_score is not None]
    if not scored:
        return hits
    kept: list[Hit] = []
    for hit in scored:
        score = hit.rerank_score
        if score is not None and score >= min_score:
            kept.append(hit)
    return kept


def _content_hash(text: str) -> str:
    """Хэш содержимого: пробелы и регистр не должны создавать «разные» чанки."""
    normalized = " ".join(text.split()).casefold()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def reciprocal_rank_fusion(
    rankings: dict[str, list[tuple[Any, float]]],
    k: int = 60,
    weights: dict[str, float] | None = None,
) -> list[tuple[Any, float, list[str]]]:
    """RRF: score(d) = Σ w_s / (k + rank_s(d)). Ранги считаются с 1.

    Ключ документа — любой хэшируемый идентификатор (у нас chunk_id),
    поэтому слияние не зависит от того, чем хранятся векторы.

    Веса позволяют сместить вклад источников, не трогая их шкалы: по
    умолчанию он равный (единица у каждого), вес 0 выбрасывает источник
    из слияния целиком — это способ выключить один из поисков, не ломая
    остальную схему.
    """
    weights = weights or {}
    fused: dict[Any, float] = {}
    sources: dict[Any, list[str]] = {}
    for name, ranking in rankings.items():
        weight = float(weights.get(name, 1.0))
        if weight <= 0:
            continue
        for rank, (doc_id, _score) in enumerate(ranking, start=1):
            fused[doc_id] = fused.get(doc_id, 0.0) + weight / (k + rank)
            sources.setdefault(doc_id, []).append(name)
    ordered = sorted(fused.items(), key=lambda kv: kv[1], reverse=True)
    return [(doc_id, score, sources[doc_id]) for doc_id, score in ordered]
