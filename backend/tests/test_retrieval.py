"""Поиск на ретриверах LangChain: гибрид, пороги, реранк, формат выдачи.

Своё хранилище не нужно: тесты собирают `InMemoryVectorStore` с осмысленными
векторами (`KeywordEmbeddings`), поэтому проверяется реальный путь LC —
плотный ретривер, `LexicalRetriever` на rank_bm25, слияние и пороги.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from helpers import KeywordEmbeddings
from langchain_classic.retrievers import ContextualCompressionRetriever, EnsembleRetriever
from langchain_core.documents import Document
from langchain_core.vectorstores import InMemoryVectorStore

from ragkb.core.config import Settings
from ragkb.core.documents import BREADCRUMB
from ragkb.core.errors import EngineUnavailable
from ragkb.core.retrieval import (
    Hit,
    HttpReranker,
    LexicalRetriever,
    build_retriever,
    dense_retriever,
    parse_rerank_scores,
    rerank_endpoint,
    search,
)

DOCUMENTS = [
    Document(
        page_content="Регламент отпусков > Оплата отпуска\nОтпускные выплачиваются за три дня.",
        metadata={
            "chunk_id": "a1",
            "doc_id": "a",
            "source": "otpusk.md",
            "title": "Регламент отпусков",
            "section": "Регламент отпусков > Оплата отпуска",
            BREADCRUMB: "Регламент отпусков > Оплата отпуска",
            "page": -1,
        },
    ),
    Document(
        page_content="Положение о командировках\nСуточные составляют 1200 рублей в сутки.",
        metadata={
            "chunk_id": "b1",
            "doc_id": "b",
            "source": "komandirovki.md",
            "title": "Положение о командировках",
            "section": "Положение о командировках",
            BREADCRUMB: "Положение о командировках",
            "page": -1,
        },
    ),
    Document(
        page_content="Политика паролей\nПароль должен содержать не менее 12 символов.",
        metadata={
            "chunk_id": "c1",
            "doc_id": "c",
            "source": "paroli.md",
            "title": "Политика паролей",
            "section": "Политика паролей",
            BREADCRUMB: "Политика паролей",
            "page": -1,
        },
    ),
]


def _cfg() -> Settings:
    cfg = Settings()
    cfg.store.backend = "memory"
    cfg.embedding.backend = "fake"
    return cfg


@pytest.fixture
def store() -> InMemoryVectorStore:
    return InMemoryVectorStore.from_documents(DOCUMENTS, KeywordEmbeddings())


# ------------------------------------------------------------------ лексический


def test_lexical_retriever_finds_exact_term():
    retriever = LexicalRetriever(documents=list(DOCUMENTS), k=3)

    found = retriever.invoke("суточные")

    assert [doc.metadata["chunk_id"] for doc in found] == ["b1"]
    assert found[0].metadata["lexical_score"] > 0


def test_lexical_retriever_uses_russian_stemming():
    """«отпуска» и «отпуск» для BM25 должны совпасть."""
    retriever = LexicalRetriever(documents=list(DOCUMENTS), k=3)

    assert [doc.metadata["chunk_id"] for doc in retriever.invoke("отпуска")] == ["a1"]


def test_lexical_retriever_without_matches_returns_nothing():
    retriever = LexicalRetriever(documents=list(DOCUMENTS), k=3)

    assert retriever.invoke("совершенно посторонние слова") == []


def test_lexical_retriever_on_empty_corpus():
    assert LexicalRetriever(documents=[], k=3).invoke("отпуск") == []


# ---------------------------------------------------------------------- сборка


def test_dense_retriever_uses_mmr_by_default(store):
    cfg = _cfg()

    assert dense_retriever(store, cfg.retrieval).search_type == "mmr"


def test_dense_retriever_is_plain_similarity_without_mmr(store):
    cfg = _cfg()
    cfg.retrieval.use_mmr = False

    assert dense_retriever(store, cfg.retrieval).search_type == "similarity"


def test_hybrid_retriever_is_ensemble(store):
    retriever = build_retriever(_cfg(), store)

    assert isinstance(retriever, EnsembleRetriever)
    assert len(retriever.retrievers) == 2
    assert retriever.c == 60
    assert retriever.id_key == "chunk_id"


def test_dense_only_when_bm25_disabled(store):
    cfg = _cfg()
    cfg.retrieval.use_bm25 = False

    assert not isinstance(build_retriever(cfg, store), EnsembleRetriever)


def test_both_searches_disabled_is_an_error(store):
    cfg = _cfg()
    cfg.retrieval.use_bm25 = False
    cfg.retrieval.use_dense = False

    with pytest.raises(EngineUnavailable) as exc:
        build_retriever(cfg, store)
    assert "отвечать по базе нечем" in exc.value.detail


def test_http_reranker_wraps_retriever(store):
    cfg = _cfg()
    cfg.retrieval.reranker = "http"
    cfg.retrieval.reranker_url = "http://rerank.test:8000/v1"

    assert isinstance(build_retriever(cfg, store), ContextualCompressionRetriever)


# ----------------------------------------------------------------------- поиск


def test_search_returns_hits_with_contract_fields(store):
    cfg = _cfg()

    hits = search(cfg, build_retriever(cfg, store), store, KeywordEmbeddings(), "суточные", 3)

    assert hits
    assert all(isinstance(hit, Hit) for hit in hits)
    assert hits[0].document.metadata["chunk_id"] == "b1"
    assert "dense" in hits[0].rank_sources
    assert hits[0].dense_score is not None
    assert hits[0].to_dict()["citation"]


def test_search_respects_top_k(store):
    cfg = _cfg()

    hits = search(cfg, build_retriever(cfg, store), store, KeywordEmbeddings(), "правила", 1)

    assert len(hits) == 1


def test_min_score_filters_unrelated_query(store):
    cfg = _cfg()
    cfg.retrieval.min_score = 0.9

    hits = search(
        cfg, build_retriever(cfg, store), store, KeywordEmbeddings(), "курс валют", 3
    )

    assert hits == []


def test_gibberish_query_returns_nothing_without_bm25(store):
    cfg = _cfg()
    cfg.retrieval.use_bm25 = False
    cfg.retrieval.min_score = 0.5

    hits = search(cfg, build_retriever(cfg, store), store, KeywordEmbeddings(), "ыыыы", 3)

    assert hits == []


def test_search_marks_lexical_matches(store):
    cfg = _cfg()
    cfg.retrieval.use_mmr = False

    hits = search(cfg, build_retriever(cfg, store), store, KeywordEmbeddings(), "суточные", 3)

    assert "lexical" in hits[0].rank_sources
    assert hits[0].lexical_score and hits[0].lexical_score > 0


# --------------------------------------------------------------------- реранкер


def test_rerank_endpoint_completes_url():
    assert rerank_endpoint("http://host:8000/v1") == "http://host:8000/v1/rerank"
    assert rerank_endpoint("http://host:8000/rerank/") == "http://host:8000/rerank"


def test_parse_rerank_scores_by_index():
    body = {
        "results": [{"index": 1, "relevance_score": 0.9}, {"index": 0, "relevance_score": 0.1}]
    }

    assert parse_rerank_scores(body, 2) == [0.1, 0.9]


def test_parse_rerank_scores_fills_missing_with_floor():
    body = {"results": [{"index": 0, "relevance_score": 0.7}]}

    assert parse_rerank_scores(body, 3) == [0.7, 0.7, 0.7]


def test_parse_rerank_scores_of_garbage_is_empty():
    assert parse_rerank_scores("не json", 2) == []
    assert parse_rerank_scores({"results": []}, 2) == []


def test_http_reranker_orders_documents(monkeypatch):
    class Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {
                "results": [
                    {"index": 1, "relevance_score": 0.9},
                    {"index": 0, "relevance_score": 0.2},
                ]
            }

    monkeypatch.setattr("ragkb.core.retrieval.httpx.post", lambda *a, **k: Response())
    reranker = HttpReranker(url="http://rerank.test/v1")

    ranked = reranker.compress_documents(DOCUMENTS[:2], "суточные")

    assert [doc.metadata["chunk_id"] for doc in ranked] == ["b1", "a1"]
    assert ranked[0].metadata["relevance_score"] == 0.9


def test_http_reranker_without_url_keeps_order():
    ranked = HttpReranker(url="").compress_documents(DOCUMENTS[:2], "суточные")

    assert [doc.metadata["chunk_id"] for doc in ranked] == ["a1", "b1"]


def test_http_reranker_failure_keeps_order(monkeypatch):
    def boom(*_args, **_kwargs):
        raise RuntimeError("реранкер лёг")

    monkeypatch.setattr("ragkb.core.retrieval.httpx.post", boom)

    ranked = HttpReranker(url="http://rerank.test/v1").compress_documents(
        DOCUMENTS[:2], "суточные"
    )

    assert [doc.metadata["chunk_id"] for doc in ranked] == ["a1", "b1"]


# ------------------------------------------------------------------------- прочее


def test_delete_by_source_removes_document_chunks(store):
    from ragkb.core.vectorstore import all_documents, delete_by_source

    removed = delete_by_source(store, str(Path("komandirovki.md")))

    assert removed == 1
    assert {doc.metadata["chunk_id"] for doc in all_documents(store)} == {"a1", "c1"}
