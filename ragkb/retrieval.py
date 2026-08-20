"""Гибридный поиск: BM25 + плотные векторы, слияние RRF, MMR, опциональный реранк.

Почему гибрид, а не только векторы: плотный поиск хорошо ловит перефразировки
(«как отпроситься» → «предоставление отпуска»), но проваливается на точных
сущностях — артикулах, номерах приказов, аббревиатурах. BM25 наоборот. Их
объединение даёт заметно более устойчивый recall, чем любой из двух отдельно.

Слияние — Reciprocal Rank Fusion: складываются не сырые оценки (они в разных
шкалах и несопоставимы), а обратные ранги. Это делает схему устойчивой к тому,
что BM25 выдаёт значения 0..30, а косинус 0..1.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from .chunking import Chunk
from .config import RetrievalConfig
from .embeddings import Embedder
from .store import BaseStore


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
    def __init__(self, store: BaseStore, embedder: Embedder, cfg: RetrievalConfig):
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
            {"dense": dense, "lexical": lexical}, k=self.cfg.rrf_k
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
        """Cross-encoder: смотрит на пару (запрос, чанк) целиком.

        Точнее bi-encoder'а, но дороже — поэтому применяется только к кандидатам
        после первичного отбора.
        """
        if self._reranker is None:
            try:
                from sentence_transformers import CrossEncoder
                self._reranker = CrossEncoder(self.cfg.reranker_model)
            except ImportError:
                return hits
        pairs = [(query, h.chunk.embed_text) for h in hits]
        scores = self._reranker.predict(pairs)
        for hit, score in zip(hits, scores, strict=False):
            hit.rerank_score = float(score)
            hit.score = float(score)
        return sorted(hits, key=lambda h: h.rerank_score or 0.0, reverse=True)


def reciprocal_rank_fusion(
    rankings: dict[str, list[tuple[Any, float]]], k: int = 60
) -> list[tuple[Any, float, list[str]]]:
    """RRF: score(d) = Σ 1 / (k + rank(d)). Ранги считаются с 1.

    Ключ документа — любой хэшируемый идентификатор (у нас chunk_id),
    поэтому слияние не зависит от того, чем хранятся векторы.
    """
    fused: dict[Any, float] = {}
    sources: dict[Any, list[str]] = {}
    for name, ranking in rankings.items():
        for rank, (doc_id, _score) in enumerate(ranking, start=1):
            fused[doc_id] = fused.get(doc_id, 0.0) + 1.0 / (k + rank)
            sources.setdefault(doc_id, []).append(name)
    ordered = sorted(fused.items(), key=lambda kv: kv[1], reverse=True)
    return [(doc_id, score, sources[doc_id]) for doc_id, score in ordered]
