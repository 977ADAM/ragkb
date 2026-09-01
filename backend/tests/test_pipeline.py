"""Юнит-тесты. Запуск: python -m pytest tests/ -q (или python tests/test_pipeline.py)."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np

from ragkb.core.bm25 import BM25Index
from ragkb.core.chunking import chunk_document
from ragkb.core.config import ChunkConfig, Config, EmbeddingConfig
from ragkb.core.embeddings import TfidfEmbedder
from ragkb.core.loaders import Block, Document, load
from ragkb.core.retrieval import reciprocal_rank_fusion
from ragkb.core.text import stem, tokenize

# ----------------------------------------------------------------- нормализация

def test_stemmer_collapses_word_forms():
    forms = ["отпуск", "отпуска", "отпуску", "отпуском", "отпуске"]
    stems = {stem(f) for f in forms}
    assert len(stems) == 1, f"формы должны сводиться к одной основе, получено {stems}"


def test_stemmer_is_idempotent():
    for word in ["документы", "согласование", "работника", "командировках"]:
        assert stem(stem(word)) == stem(word)


def test_stemmer_keeps_short_words():
    assert stem("дом") == "дом"
    assert stem("VPN".lower()) == "vpn"


def test_tokenizer_drops_stopwords():
    tokens = tokenize("и в на отпуск сотрудника")
    assert "и" not in tokens and "в" not in tokens
    assert len(tokens) == 2


def test_tokenizer_keeps_numbers_and_hyphens():
    tokens = tokenize("бизнес-класс 1200 рублей", stemming=False)
    assert "бизнес-класс" in tokens
    assert "1200" in tokens


# ---------------------------------------------------------------------- чанкинг

def _doc(blocks):
    return Document(doc_id="d1", path="/tmp/x.md", title="Док", blocks=blocks, checksum="c")


def test_chunk_carries_heading_breadcrumb():
    doc = _doc([
        Block("Раздел 1", kind="heading", level=1),
        Block("Оплата производится в течение трёх дней."),
    ])
    chunks = chunk_document(doc, ChunkConfig(size=900, overlap=0, min_size=1))
    assert chunks[0].section == "Раздел 1"
    assert "Раздел 1" in chunks[0].embed_text
    # В text заголовка нет — LLM видит только содержательный текст.
    assert "Оплата" in chunks[0].text


def test_chunks_respect_size_limit():
    long_text = " ".join(f"Предложение номер {i} с некоторым текстом." for i in range(200))
    chunks = chunk_document(_doc([Block(long_text)]), ChunkConfig(size=400, overlap=50, min_size=1))
    assert len(chunks) > 1
    assert all(len(c.text) <= 900 for c in chunks), [len(c.text) for c in chunks]


def test_chunking_terminates_on_pathological_input():
    """Регрессия: оверлап не должен приводить к бесконечному циклу."""
    blocks = [Block("Короткая строка.") for _ in range(50)]
    chunks = chunk_document(_doc(blocks), ChunkConfig(size=100, overlap=90, min_size=1))
    assert 0 < len(chunks) < 200


def test_citation_does_not_duplicate_title():
    doc = Document(doc_id="d", path="/tmp/a.md", title="Регламент", checksum="c", blocks=[
        Block("Регламент", kind="heading", level=1),
        Block("Пункт 1", kind="heading", level=2),
        Block("Текст пункта достаточной длины для чанка."),
    ])
    chunk = chunk_document(doc, ChunkConfig(min_size=1))[0]
    assert chunk.citation().count("Регламент") == 1


# ------------------------------------------------------------------------ BM25

def test_bm25_ranks_exact_term_first():
    texts = [
        "Суточные при командировках по России составляют 1200 рублей.",
        "Отпуск составляет 28 календарных дней.",
        "Пароль должен содержать не менее 12 символов.",
    ]
    index = BM25Index().build(texts)
    ranked = index.search("размер суточных в командировке", top_k=3)
    assert ranked[0][0] == 0


def test_bm25_matches_inflected_forms():
    index = BM25Index().build(["Заявление на отпуск подаётся заранее."])
    assert index.search("отпуска", top_k=1), "стемминг должен связать «отпуск» и «отпуска»"


def test_bm25_empty_index_is_safe():
    assert BM25Index().build([]).search("что угодно") == []


def test_bm25_roundtrip(tmp_path=None):
    tmp = Path(tempfile.mkdtemp())
    index = BM25Index().build(["первый документ про закупки", "второй про отпуск"])
    index.save(tmp / "bm25.pkl")
    restored = BM25Index.load(tmp / "bm25.pkl")
    assert restored.search("закупки") == index.search("закупки")


# ------------------------------------------------------------------ эмбеддинги

def test_embeddings_are_normalized():
    emb = TfidfEmbedder(EmbeddingConfig(tfidf_dim=256))
    vectors = emb.embed_documents(["первый текст", "второй текст про отпуск"])
    norms = np.linalg.norm(vectors, axis=1)
    assert np.allclose(norms, 1.0, atol=1e-5)


def test_similar_texts_score_higher():
    emb = TfidfEmbedder(EmbeddingConfig(tfidf_dim=2048))
    docs = ["Суточные в командировке составляют 1200 рублей",
            "Пароль должен содержать 12 символов"]
    matrix = emb.embed_documents(docs)
    query = emb.embed_query("размер суточных в командировке")
    scores = matrix @ query
    assert scores[0] > scores[1]


def test_tfidf_state_roundtrip():
    emb = TfidfEmbedder(EmbeddingConfig(tfidf_dim=512))
    emb.embed_documents(["отпуск и командировки", "закупки и тендеры"])
    restored = TfidfEmbedder(EmbeddingConfig(tfidf_dim=512))
    restored.load_state(emb.state())
    assert np.allclose(emb.embed_query("отпуск"), restored.embed_query("отпуск"))


def test_hash_is_stable_across_calls():
    from ragkb.core.embeddings import _stable_hash
    assert _stable_hash("отпуск".encode()) == _stable_hash("отпуск".encode())
    assert _stable_hash("отпуск".encode()) != _stable_hash("закупка".encode())


# -------------------------------------------------------------------- слияние

def test_rrf_prefers_item_ranked_by_both():
    fused = reciprocal_rank_fusion({
        "dense": [(1, 0.9), (2, 0.8), (3, 0.7)],
        "lexical": [(3, 12.0), (1, 9.0)],
    })
    top = fused[0]
    assert top[0] in {1, 3}
    assert set(top[2]) == {"dense", "lexical"}


def test_rrf_is_scale_invariant():
    """Разные шкалы оценок не должны влиять на результат — важен только ранг."""
    a = reciprocal_rank_fusion({"x": [(1, 0.9), (2, 0.1)]})
    b = reciprocal_rank_fusion({"x": [(1, 900.0), (2, 100.0)]})
    assert [i for i, *_ in a] == [i for i, *_ in b]


# --------------------------------------------------------------- end-to-end

SAMPLE_DOC = (
    "# Политика\n\n## Пароли\n\nПароль должен содержать не менее 12 символов.\n\n"
    "## Отпуск\n\nЕжегодный отпуск составляет 28 календарных дней.\n"
)


def _workspace(backend: str) -> Config:
    workdir = Path(tempfile.mkdtemp())
    docs = workdir / "docs"
    docs.mkdir()
    (docs / "policy.md").write_text(SAMPLE_DOC, encoding="utf-8")
    cfg = Config(docs_dir=str(docs), index_dir=str(workdir / "index"))
    cfg.store.backend = backend
    return cfg


def _chroma_available() -> bool:
    try:
        import chromadb  # noqa: F401
        return True
    except ImportError:
        return False


def test_index_and_search_end_to_end_numpy():
    _assert_end_to_end("numpy")


def test_index_and_search_end_to_end_chroma():
    if not _chroma_available():
        import pytest
        pytest.skip("chromadb не установлена")
    _assert_end_to_end("chroma")


def _assert_end_to_end(backend: str) -> None:
    from ragkb.core.pipeline import RAGPipeline, build_index

    cfg = _workspace(backend)
    report = build_index(cfg)
    assert report.chunks >= 2
    assert report.store_backend == backend

    pipeline = RAGPipeline(cfg)
    hits = pipeline.search("какой длины должен быть пароль", top_k=2)
    assert hits and "12 символов" in hits[0].chunk.text

    answer = pipeline.ask("сколько дней отпуска?")
    assert "28" in answer.text
    assert answer.hits


def test_backends_agree_on_ranking():
    """Chroma и numpy должны выдавать одинаковый порядок на одних данных.

    Chroma отдаёт косинусную дистанцию, numpy — близость; если где-то забыть
    преобразование, ранжирование молча перевернётся.
    """
    if not _chroma_available():
        import pytest
        pytest.skip("chromadb не установлена")
    from ragkb.core.pipeline import RAGPipeline, build_index

    queries = ["длина пароля", "сколько дней отпуска", "требования безопасности"]
    results = {}
    for backend in ("numpy", "chroma"):
        cfg = _workspace(backend)
        build_index(cfg)
        pipeline = RAGPipeline(cfg)
        results[backend] = [
            [h.chunk.text for h in pipeline.search(q, top_k=3)] for q in queries
        ]
    assert results["numpy"] == results["chroma"], "бэкенды разошлись в ранжировании"


def test_chroma_returns_similarity_not_distance():
    """Плотная оценка должна расти с похожестью, а не падать."""
    if not _chroma_available():
        import pytest
        pytest.skip("chromadb не установлена")
    from ragkb.core.pipeline import RAGPipeline, build_index

    cfg = _workspace("chroma")
    build_index(cfg)
    pipeline = RAGPipeline(cfg)
    hits = pipeline.search("пароль должен содержать 12 символов", top_k=3)
    dense = [h.dense_score for h in hits if h.dense_score is not None]
    assert dense and max(dense) > 0.3, f"похожие тексты должны давать высокий скор: {dense}"


def test_chroma_incremental_update_and_delete():
    if not _chroma_available():
        import pytest
        pytest.skip("chromadb не установлена")
    from ragkb.core.pipeline import RAGPipeline, build_index, remove_document, update_documents

    cfg = _workspace("chroma")
    build_index(cfg)
    baseline = len(RAGPipeline(cfg).store)

    extra = Path(cfg.docs_dir).parent / "extra.md"
    extra.write_text(
        "# Техника\n\nНоутбук заменяется каждые четыре года по плановому графику.\n",
        encoding="utf-8",
    )
    update_documents(cfg, [str(extra)])
    assert len(RAGPipeline(cfg).store) > baseline

    # Повторная загрузка того же файла не должна плодить дубли.
    update_documents(cfg, [str(extra)])
    after_second = len(RAGPipeline(cfg).store)
    update_documents(cfg, [str(extra)])
    assert len(RAGPipeline(cfg).store) == after_second

    removed = remove_document(cfg, str(extra))
    assert removed > 0
    assert len(RAGPipeline(cfg).store) == baseline


def test_numpy_rejects_incremental_update():
    """У numpy-хранилища нет upsert — ошибка должна быть явной."""
    from ragkb.core.pipeline import build_index, update_documents

    cfg = _workspace("numpy")
    build_index(cfg)
    try:
        update_documents(cfg, [cfg.docs_dir])
    except ValueError as exc:
        assert "chroma" in str(exc)
    else:
        raise AssertionError("ожидалась ошибка о недоступности инкрементального обновления")


def test_store_backend_mismatch_is_detected():
    """Индекс Chroma нельзя открыть numpy-бэкендом и наоборот."""
    from ragkb.core.pipeline import RAGPipeline, build_index

    cfg = _workspace("numpy")
    build_index(cfg)
    cfg.store.backend = "chroma"
    try:
        RAGPipeline(cfg)
    except ValueError as exc:
        assert "Переиндексируйте" in str(exc)
    else:
        raise AssertionError("ожидалась ошибка несовпадения бэкенда хранилища")


def test_invalid_collection_name_is_rejected_early():
    from ragkb.core.store import _validate_collection_name

    _validate_collection_name("knowledge_base")
    for bad in ("b", "ab", "-plohoe", "с_кириллицей"):
        try:
            _validate_collection_name(bad)
        except ValueError as exc:
            assert "store.collection" in str(exc)
        else:
            raise AssertionError(f"имя «{bad}» должно быть отклонено")


def test_pipeline_rejects_mismatched_embedder():
    """Индекс, построенный одной моделью, нельзя опрашивать другой."""
    from ragkb.core.pipeline import RAGPipeline, build_index

    cfg = _workspace("numpy")
    build_index(cfg)

    cfg.embedding.backend = "openai"
    cfg.embedding.model = "bge-m3"
    try:
        RAGPipeline(cfg)
    except ValueError as exc:
        assert "Переиндексируйте" in str(exc)
    else:
        raise AssertionError("ожидалась ошибка несовпадения эмбеддера")


def test_loaders_read_all_formats():
    root = Path(__file__).resolve().parents[1] / "data" / "docs"
    if not root.exists():
        return
    for path in root.iterdir():
        doc = load(path)
        assert doc.blocks, f"пустой документ: {path.name}"
        assert doc.title


# ------------------------------------------------------------- загрузка .env

def test_dotenv_repo_root_is_loaded_when_config_is_nested():
    import os

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / ".env").write_text(
            "RAGKB_LLM_URL=http://10.0.0.2:1/v1\n", encoding="utf-8"
        )
        nested = root / "backend"
        nested.mkdir()
        try:
            cfg = Config.load(nested / "config.yaml")
            assert cfg.llm.base_url == "http://10.0.0.2:1/v1"
        finally:
            os.environ.pop("RAGKB_LLM_URL", None)


def test_dotenv_next_to_config_is_loaded():
    import os

    with tempfile.TemporaryDirectory() as tmp:
        Path(tmp, ".env").write_text(
            "RAGKB_LLM_URL=http://10.0.0.1:9999/v1\n", encoding="utf-8"
        )
        try:
            cfg = Config.load(Path(tmp) / "config.yaml")
            assert cfg.llm.base_url == "http://10.0.0.1:9999/v1"
        finally:
            os.environ.pop("RAGKB_LLM_URL", None)


def test_dotenv_does_not_override_real_environment():
    import os

    os.environ["RAGKB_LLM_URL"] = "http://127.0.0.1:1234"
    try:
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, ".env").write_text(
                "RAGKB_LLM_URL=http://10.0.0.1:9999/v1\n", encoding="utf-8"
            )
            cfg = Config.load(Path(tmp) / "config.yaml")
            assert cfg.llm.base_url == "http://127.0.0.1:1234"
    finally:
        os.environ.pop("RAGKB_LLM_URL", None)


def test_dotenv_absent_means_defaults():
    with tempfile.TemporaryDirectory() as tmp:
        cfg = Config.load(Path(tmp) / "config.yaml")
        assert cfg.llm.base_url == ""
