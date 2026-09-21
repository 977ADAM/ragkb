"""Индексация и цепочка ответа: документы, нарезка, манифест, LCEL.

Сети нет: эмбеддинги считает `KeywordEmbeddings` (косинус по пересечению
слов), хранилище — `InMemoryVectorStore`, модель ответа — `ScriptedChatModel`.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from helpers import KeywordEmbeddings, ScriptedChatModel, corpus_names

from ragkb.core import loaders, manifest
from ragkb.core.config import Settings
from ragkb.core.documents import (
    BREADCRUMB,
    document_citation,
    document_page,
    document_text,
    section_documents,
    split_documents,
)
from ragkb.core.errors import EngineUnavailable
from ragkb.core.index import ConfigIndex
from ragkb.core.pipeline import RagChain, build_index, parse_expanded_queries
from ragkb.core.retrieval import Hit

SAMPLE = """# Регламент отпусков

## Оплата отпуска

Отпускные выплачиваются не позднее чем за три дня до начала отдыха.

## Подача заявления

Заявление подаётся не позднее чем за 14 календарных дней.

# Командировки

Суточные составляют 1200 рублей в сутки.
"""


def _cfg(tmp_path: Path, **files: str) -> Settings:
    docs = tmp_path / "docs"
    docs.mkdir(parents=True, exist_ok=True)
    for name, content in (files or {"policy.md": SAMPLE}).items():
        (docs / name).write_text(content, encoding="utf-8")
    cfg = Settings(docs_dir=str(docs), index_dir=str(tmp_path / "index"))
    cfg.store.backend = "memory"
    cfg.embedding.backend = "fake"
    cfg.logging.dir = str(tmp_path / "logs")
    return cfg


@pytest.fixture
def keyword_embeddings(monkeypatch):
    """Одинаковые осмысленные векторы и при сборке индекса, и при поиске."""
    embeddings = KeywordEmbeddings()
    monkeypatch.setattr("ragkb.core.pipeline.build_embeddings", lambda _cfg: embeddings)
    return embeddings


# ------------------------------------------------------------------- документы


def test_sections_follow_heading_hierarchy(tmp_path):
    cfg = _cfg(tmp_path)
    loaded = loaders.load(Path(cfg.docs_dir) / "policy.md")

    sections = section_documents(loaded)

    assert [s.metadata["section"] for s in sections] == [
        "Регламент отпусков > Оплата отпуска",
        "Регламент отпусков > Подача заявления",
        "Командировки",
    ]
    assert sections[0].metadata["title"] == "Регламент отпусков"
    assert "не позднее чем за три дня" in sections[0].page_content


def test_breadcrumb_lands_in_every_chunk(tmp_path):
    long_text = "# Регламент\n\n## Отпуск\n\n" + "Предложение про отпуск. " * 80
    cfg = _cfg(tmp_path, **{"long.md": long_text})
    cfg.chunking.size = 200
    cfg.chunking.overlap = 20
    loaded = loaders.load(Path(cfg.docs_dir) / "long.md")

    chunks = split_documents(section_documents(loaded), cfg.chunking)

    assert len(chunks) > 1
    for chunk in chunks:
        assert chunk.metadata[BREADCRUMB] == "Регламент > Отпуск"
        assert chunk.page_content.startswith("Регламент > Отпуск")
        # В текст для пользователя breadcrumb не попадает.
        assert not document_text(chunk).startswith("Регламент > Отпуск")
    assert [c.metadata["position"] for c in chunks] == list(range(len(chunks)))
    assert len({c.metadata["chunk_id"] for c in chunks}) == len(chunks)


def test_splitter_respects_size(tmp_path):
    cfg = _cfg(tmp_path)
    cfg.chunking.size = 120
    cfg.chunking.overlap = 0
    loaded = loaders.load(Path(cfg.docs_dir) / "policy.md")

    chunks = split_documents(section_documents(loaded), cfg.chunking)

    assert chunks
    assert max(len(document_text(chunk)) for chunk in chunks) <= 300


def test_citation_skips_repeated_document_title(tmp_path):
    cfg = _cfg(tmp_path)
    loaded = loaders.load(Path(cfg.docs_dir) / "policy.md")
    sections = section_documents(loaded)
    chunk = split_documents([sections[1]], cfg.chunking)[0]

    assert document_citation(chunk) == "Регламент отпусков / Подача заявления"
    assert document_page(chunk) is None


# ------------------------------------------------------------------ индексация


def test_build_index_writes_manifest(tmp_path, keyword_embeddings):
    cfg = _cfg(tmp_path)

    report = build_index(cfg, corpus_names(cfg))

    assert report.files == 1
    assert report.chunks >= 3
    assert report.store_backend == "memory"
    assert report.embedder == "fake:1024"

    indexed = manifest.read(cfg)
    assert indexed["n_chunks"] == report.chunks
    assert indexed["store"] == "memory"
    assert indexed["chunk_size"] == cfg.chunking.size
    assert [d["title"] for d in indexed["documents"]] == ["Регламент отпусков"]
    assert indexed["documents"][0]["chunks"] == report.chunks
    # Факты о файле нужны странице документов, чтобы отличить правку от подмены.
    assert {"mtime", "size", "sha256"} <= set(indexed["documents"][0])


def test_build_index_reports_missing_file(tmp_path, keyword_embeddings):
    """Запись в корпусе есть, файла нет — это ошибка с причиной, а не пустой индекс."""
    cfg = _cfg(tmp_path)
    Path(cfg.docs_dir, "policy.md").unlink()

    with pytest.raises(ValueError) as exc:
        build_index(cfg, frozenset({"policy.md"}))

    assert "файл не найден" in str(exc.value)


def test_build_index_indexes_only_named_documents(tmp_path, keyword_embeddings):
    """Индексируются документы корпуса, а не всё, что лежит в каталоге."""
    cfg = _cfg(
        tmp_path,
        **{"accepted.md": "# Принят\n\nТекст.\n", "rejected.md": "# Нет\n\nТекст.\n"},
    )

    report = build_index(cfg, frozenset({"accepted.md"}))

    assert report.files == 1
    assert [Path(d["source"]).name for d in manifest.read(cfg)["documents"]] == ["accepted.md"]


def test_build_index_with_empty_corpus_explains_what_to_do(tmp_path, keyword_embeddings):
    cfg = _cfg(tmp_path)

    with pytest.raises(ValueError) as exc:
        build_index(cfg, frozenset())

    assert "загрузите их на странице" in str(exc.value).lower()


def test_build_index_reports_unreadable_file(tmp_path, keyword_embeddings):
    cfg = _cfg(tmp_path)
    (Path(cfg.docs_dir) / "broken.pdf").write_bytes(b"not a pdf")

    report = build_index(cfg, corpus_names(cfg))

    assert report.files == 1
    assert [Path(path).name for path, _reason in report.skipped] == ["broken.pdf"]


def test_every_file_gets_its_own_document(tmp_path, keyword_embeddings):
    cfg = _cfg(
        tmp_path, **{"first.md": "# Первый\n\nТекст.\n", "second.md": "# Второй\n\nТекст.\n"}
    )

    report = build_index(cfg, corpus_names(cfg))

    assert report.files == 2
    assert len(manifest.read(cfg)["documents"]) == 2


# ----------------------------------------------------------------------- RAG


def test_search_finds_fragment_by_exact_term(tmp_path, keyword_embeddings):
    cfg = _cfg(tmp_path)
    build_index(cfg, corpus_names(cfg))
    chain = RagChain(cfg)

    hits = chain.search("сколько суточные в командировке", top_k=3)

    assert hits
    assert "суточные" in hits[0].text.lower()


def test_hit_payload_keeps_api_contract(tmp_path, keyword_embeddings):
    cfg = _cfg(tmp_path)
    build_index(cfg, corpus_names(cfg))
    chain = RagChain(cfg)

    payload = chain.search("отпуск", top_k=1)[0].to_dict()

    assert set(payload) == {
        "chunk_id",
        "text",
        "citation",
        "source",
        "page",
        "section",
        "score",
        "dense_score",
        "lexical_score",
        "rerank_score",
        "matched_by",
    }
    assert payload["citation"]
    assert payload["source"].endswith("policy.md")


def test_min_score_drops_unrelated_hits(tmp_path, keyword_embeddings):
    cfg = _cfg(tmp_path)
    build_index(cfg, corpus_names(cfg))
    cfg.retrieval.min_score = 0.9
    chain = RagChain(cfg)

    assert chain.search("совершенно посторонний вопрос") == []


def test_chain_rejects_index_of_another_embedder(tmp_path, keyword_embeddings):
    cfg = _cfg(tmp_path)
    build_index(cfg, corpus_names(cfg))
    cfg.embedding.fake_dim = 64

    with pytest.raises(ValueError) as exc:
        RagChain(cfg)
    assert "Переиндексируйте" in str(exc.value)


def test_chain_rejects_index_of_another_store(tmp_path, keyword_embeddings):
    cfg = _cfg(tmp_path)
    build_index(cfg, corpus_names(cfg))
    cfg.store.backend = "chroma"

    with pytest.raises(ValueError) as exc:
        RagChain(cfg)
    assert "Перестройте индекс" in str(exc.value)


def test_chain_requires_manifest(tmp_path, keyword_embeddings):
    cfg = _cfg(tmp_path)

    with pytest.raises(EngineUnavailable) as exc:
        RagChain(cfg)
    assert "Индекс не найден" in exc.value.detail


def test_stream_answer_yields_tokens_and_hits(tmp_path, keyword_embeddings, monkeypatch):
    cfg = _cfg(tmp_path)
    build_index(cfg, corpus_names(cfg))
    monkeypatch.setattr(
        "ragkb.core.pipeline.build_chat_model",
        lambda *_args, **_kwargs: ScriptedChatModel(responses=["Отпускные — за три дня [1]."]),
    )
    chain = RagChain(cfg)

    hits, tokens = chain.stream_answer("когда выплачивают отпускные")

    text = "".join(tokens)
    assert "Отпускные" in text
    assert hits
    assert chain.cited_sources(text, hits)[0]["n"] == 1


def test_ask_returns_answer_with_sources(tmp_path, keyword_embeddings, monkeypatch):
    cfg = _cfg(tmp_path)
    build_index(cfg, corpus_names(cfg))
    monkeypatch.setattr(
        "ragkb.core.pipeline.build_chat_model",
        lambda *_args, **_kwargs: ScriptedChatModel(responses=["Суточные — 1200 рублей [1]."]),
    )
    chain = RagChain(cfg)

    answer = chain.ask("сколько суточные")

    assert answer.text.startswith("Суточные")
    assert answer.used_sources[0]["n"] == 1
    assert answer.llm_backend.startswith("openai:")
    assert answer.elapsed >= 0


def test_llm_unavailable_without_address(tmp_path, keyword_embeddings):
    cfg = _cfg(tmp_path)
    build_index(cfg, corpus_names(cfg))
    cfg.llm.base_url = ""
    chain = RagChain(cfg)

    assert chain.llm_available() is False


def test_cited_sources_skip_uncited_and_unknown_numbers(tmp_path, keyword_embeddings):
    cfg = _cfg(tmp_path)
    build_index(cfg, corpus_names(cfg))
    chain = RagChain(cfg)
    hits = chain.search("отпуск", top_k=3)

    sources = chain.cited_sources("Ответ [3] и [9].", hits)

    assert [s["n"] for s in sources] == [3]
    assert sources[0]["text"]


def test_stats_describe_index_without_building_engine(tmp_path, keyword_embeddings):
    cfg = _cfg(tmp_path)
    build_index(cfg, corpus_names(cfg))

    stats = ConfigIndex(cfg, lambda: pytest.fail("движок не нужен")).stats()

    assert stats["chunks"] > 0
    assert stats["store"] == "memory"
    assert stats["embedder"] == "fake:1024"


# ------------------------------------------------------------- расширение запроса


def test_expanded_queries_from_json():
    raw = 'Вот результат: {"queries": ["предоставление отпуска", "оплата отпуска"]}'

    assert parse_expanded_queries(raw, "отпуск", 2) == [
        "предоставление отпуска",
        "оплата отпуска",
    ]


def test_expanded_queries_fall_back_to_lines():
    raw = "1. предоставление ежегодного отпуска\n2. оплата отпускных"

    assert parse_expanded_queries(raw, "отпуск", 2) == [
        "предоставление ежегодного отпуска",
        "оплата отпускных",
    ]


def test_expanded_queries_drop_repeats_of_question():
    raw = '{"queries": ["отпуск", "оплата отпускных"]}'

    assert parse_expanded_queries(raw, "отпуск", 3) == ["оплата отпускных"]


def test_expand_search_merges_variants(tmp_path, keyword_embeddings, monkeypatch):
    cfg = _cfg(tmp_path)
    build_index(cfg, corpus_names(cfg))
    monkeypatch.setattr(
        "ragkb.core.pipeline.build_chat_model",
        lambda *_args, **_kwargs: ScriptedChatModel(
            responses=['{"queries": ["суточные в командировке"]}']
        ),
    )
    chain = RagChain(cfg)

    assert chain.search("командировка", top_k=3, expand=True)


# ------------------------------------------------------------- окружение RAGKB_*


def test_env_overrides_nested_section(monkeypatch):
    monkeypatch.setenv("RAGKB_EMBEDDING_MODEL", "bge-m3")
    monkeypatch.setenv("RAGKB_EMBEDDING_KEEP_ALIVE", "5m")

    cfg = Settings()

    assert cfg.embedding.model == "bge-m3"
    assert cfg.embedding.keep_alive == "5m"


def test_env_coerces_types(monkeypatch):
    monkeypatch.setenv("RAGKB_EMBEDDING_FAKE_DIM", "128")

    assert Settings().embedding.fake_dim == 128


def test_hit_dataclass_contract():
    from langchain_core.documents import Document

    hit = Hit(
        document=Document(
            page_content="Регламент > Оплата\nТекст",
            metadata={
                "chunk_id": "abc",
                "source": "policy.md",
                "title": "Регламент",
                "section": "Регламент > Оплата",
                BREADCRUMB: "Регламент > Оплата",
                "page": -1,
            },
        ),
        score=0.5,
    )

    assert hit.text == "Текст"
    assert hit.citation == "Регламент / Оплата"
    assert hit.to_dict()["page"] is None


def test_manifest_json_is_readable(tmp_path, keyword_embeddings):
    cfg = _cfg(tmp_path)
    build_index(cfg, corpus_names(cfg))

    payload = json.loads((Path(cfg.index_dir) / "manifest.json").read_text(encoding="utf-8"))

    assert payload["embedder"] == "fake:1024"
    assert payload["dim"] == 256
