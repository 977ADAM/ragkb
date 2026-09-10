"""Ранжирование: слияние с весами, дедупликация, реранк.

Эти свойства видны только на живом поиске — их нельзя проверить на чанкинге
или загрузчиках, поэтому здесь своё хранилище-заглушка: тест задаёт порядок
кандидатов напрямую и смотрит, что из него получится после слияния.
"""
from __future__ import annotations

import numpy as np
import pytest

from ragkb.core.chunking import Chunk
from ragkb.core.config import Settings
from ragkb.core.pipeline import parse_expanded_queries
from ragkb.core.retrieval import (
    Hit,
    Retriever,
    collapse_duplicate_text,
    drop_below_rerank_score,
    parse_rerank_scores,
    reciprocal_rank_fusion,
    rerank_endpoint,
)

# ------------------------------------------------------------------ слияние RRF


def test_rrf_default_weights_keep_scale():
    """Без весов оценка прежняя: 1 / (k + rank), иначе изменился бы весь порядок."""
    fused = reciprocal_rank_fusion({"x": [("a", 10.0)]}, k=60)
    assert fused == [("a", pytest.approx(1 / 61), ["x"])]


def test_rrf_weight_can_flip_order():
    """Вес источника смещает вклад, не трогая шкалы оценок."""
    rankings = {"dense": [("a", 0.9), ("b", 0.8)], "lexical": [("b", 30.0)]}
    assert reciprocal_rank_fusion(rankings, k=1)[0][0] == "b"
    weakened = reciprocal_rank_fusion(rankings, k=1, weights={"lexical": 0.2})
    assert weakened[0][0] == "a"


def test_rrf_zero_weight_drops_source():
    """Нулевой вес — способ выключить один из поисков целиком."""
    fused = reciprocal_rank_fusion(
        {"dense": [("a", 0.9)], "lexical": [("b", 30.0)]}, weights={"lexical": 0}
    )
    assert [(doc, sources) for doc, _score, sources in fused] == [("a", ["dense"])]


# ------------------------------------------------------------- дедупликация


def _chunk(chunk_id: str, text: str, source: str = "data/docs/a.md") -> Chunk:
    return Chunk(
        chunk_id=chunk_id,
        doc_id=f"d-{source}",
        text=text,
        embed_text=text,
        source=source,
        title="Док",
        section="",
        page=None,
        position=0,
    )


def _hit(chunk_id: str, text: str, score: float = 1.0, **kwargs) -> Hit:
    return Hit(chunk=_chunk(chunk_id, text), score=score, **kwargs)


class _FakeEmbedder:
    def embed_query(self, _query: str) -> np.ndarray:
        return np.ones(2, dtype=np.float32)


class _FakeStore:
    """Хранилище, у которого порядок кандидатов задан тестом."""

    def __init__(
        self,
        chunks: list[Chunk],
        dense: list[tuple[str, float]],
        lexical: list[tuple[str, float]],
    ):
        self._chunks = {c.chunk_id: c for c in chunks}
        self._dense = dense
        self._lexical = lexical

    def __len__(self) -> int:
        return len(self._chunks)

    def get_chunk(self, chunk_id: str) -> Chunk:
        return self._chunks[chunk_id]

    def dense_search(self, _query_vector, top_k: int) -> list[tuple[str, float]]:
        return self._dense[:top_k]

    def lexical_search(self, _query: str, top_k: int) -> list[tuple[str, float]]:
        return self._lexical[:top_k]

    def get_vectors(self, chunk_ids) -> np.ndarray:
        return np.zeros((len(chunk_ids), 2), dtype=np.float32)


SAME_TEXT = "Ежегодный отпуск составляет 28 календарных дней."
OTHER_TEXT = "Проезд в командировке оплачивается по фактическим расходам."


def _duplicate_store() -> _FakeStore:
    """Два файла с одинаковым абзацем — так бывает при копии документа."""
    return _FakeStore(
        chunks=[
            _chunk("a", SAME_TEXT, source="data/docs/hr.md"),
            _chunk("b", SAME_TEXT, source="data/docs/copy.md"),
            _chunk("c", OTHER_TEXT, source="data/docs/trips.md"),
        ],
        dense=[("a", 0.9), ("b", 0.88), ("c", 0.5)],
        lexical=[("b", 12.0), ("a", 11.0), ("c", 3.0)],
    )


def _retrieval_cfg() -> Settings.RetrievalConfig:
    cfg = Settings.RetrievalConfig()
    cfg.use_mmr = False  # MMR проверяется отдельно, здесь нужен порядок слияния
    return cfg


def test_collapse_duplicate_text_keeps_one_hit():
    hits = [
        _hit("a", SAME_TEXT, score=0.9),
        _hit("b", "  ежегодный   отпуск СОСТАВЛЯЕТ 28 календарных дней.  ", score=0.5),
        _hit("c", OTHER_TEXT, score=0.4),
    ]
    assert [h.chunk.chunk_id for h in collapse_duplicate_text(hits)] == ["a", "c"]


def test_collapse_duplicate_text_merges_match_info():
    """Признак находки не теряется: фрагмент подтверждён обоими поисками."""
    first = _hit("a", SAME_TEXT, rank_sources=["dense"], dense_score=0.9)
    second = _hit("b", SAME_TEXT, score=0.5, rank_sources=["lexical"], lexical_score=12.0)
    merged = collapse_duplicate_text([first, second])
    assert len(merged) == 1
    assert merged[0].rank_sources == ["dense", "lexical"]
    assert merged[0].lexical_score == 12.0


def test_search_drops_duplicate_text():
    retriever = Retriever(_duplicate_store(), _FakeEmbedder(), _retrieval_cfg())
    hits = retriever.search("отпуск", top_k=3)
    assert [h.chunk.chunk_id for h in hits] == ["a", "c"]
    assert set(hits[0].rank_sources) == {"dense", "lexical"}


def test_search_keeps_duplicates_when_dedupe_disabled():
    cfg = _retrieval_cfg()
    cfg.dedupe_text = False
    retriever = Retriever(_duplicate_store(), _FakeEmbedder(), cfg)
    hits = retriever.search("отпуск", top_k=3)
    assert [h.chunk.chunk_id for h in hits] == ["a", "b", "c"]


def test_search_uses_configured_weights():
    cfg = _retrieval_cfg()
    cfg.bm25_weight = 0.0
    retriever = Retriever(_duplicate_store(), _FakeEmbedder(), cfg)
    hits = retriever.search("отпуск", top_k=3)
    # Лексический поиск выключен весом: порядок задаёт только плотный.
    assert [h.chunk.chunk_id for h in hits] == ["a", "c"]


# ------------------------------------------------------------------- реранк


def test_rerank_threshold_filters_candidates():
    hits = [
        _hit("a", SAME_TEXT, rerank_score=0.9),
        _hit("b", OTHER_TEXT, rerank_score=0.1),
    ]
    assert [h.chunk.chunk_id for h in drop_below_rerank_score(hits, 0.5)] == ["a"]


def test_rerank_threshold_disabled_by_default():
    hits = [_hit("a", SAME_TEXT, rerank_score=-5.0)]
    assert drop_below_rerank_score(hits, 0.0) == hits


def test_rerank_threshold_keeps_hits_without_scores():
    """Реранкер не отработал — пустая выдача означала бы «нет информации»."""
    hits = [_hit("a", SAME_TEXT)]
    assert drop_below_rerank_score(hits, 0.5) == hits


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("http://rerank:8080/v1", "http://rerank:8080/v1/rerank"),
        ("http://rerank:8080/v1/", "http://rerank:8080/v1/rerank"),
        ("http://rerank:8080/v1/rerank", "http://rerank:8080/v1/rerank"),
    ],
)
def test_rerank_endpoint_is_completed(url: str, expected: str):
    assert rerank_endpoint(url) == expected


def test_parse_rerank_scores_orders_by_index():
    body = {
        "results": [
            {"index": 1, "relevance_score": 0.2},
            {"index": 0, "relevance_score": 0.9},
        ]
    }
    assert parse_rerank_scores(body, 2) == [0.9, 0.2]


def test_parse_rerank_scores_accepts_score_and_data():
    assert parse_rerank_scores({"data": [{"index": 0, "score": 0.42}]}, 1) == [0.42]


def test_parse_rerank_scores_fills_missing_with_floor():
    """Неоценённый документ не должен всплывать выше проверенных."""
    body = {"results": [{"index": 0, "relevance_score": 0.7}]}
    assert parse_rerank_scores(body, 2) == [0.7, 0.7]


def test_parse_rerank_scores_rejects_broken_response():
    body = {"results": [{"index": 5, "relevance_score": 1.0}, {"index": "0"}, "мусор"]}
    assert parse_rerank_scores(body, 2) == []


# ------------------------------------------------- перефразировки для поиска


def test_expanded_queries_are_read_from_json():
    raw = 'Готово: {"queries": ["оплата отпуска", "срок выплаты отпускных"]}'
    assert parse_expanded_queries(raw, "когда платят за отпуск?", 2) == [
        "оплата отпуска",
        "срок выплаты отпускных",
    ]


def test_expanded_queries_fall_back_to_lines():
    """Модель без поддержки JSON — не повод остаться без перефразировок."""
    raw = "1. оплата отпуска\n2) срок выплаты отпускных"
    assert parse_expanded_queries(raw, "когда платят?", 5) == [
        "оплата отпуска",
        "срок выплаты отпускных",
    ]


def test_expanded_queries_drop_repeats_of_question():
    raw = '{"queries": ["Сколько дней отпуска?", "длительность ежегодного отпуска"]}'
    assert parse_expanded_queries(raw, "сколько дней отпуска?", 3) == [
        "длительность ежегодного отпуска"
    ]


def test_expanded_queries_ignore_short_and_extra():
    raw = '{"queries": ["ок", "первая нормальная фраза", "вторая нормальная фраза"]}'
    assert parse_expanded_queries(raw, "вопрос", 2) == [
        "первая нормальная фраза",
        "вторая нормальная фраза",
    ]
