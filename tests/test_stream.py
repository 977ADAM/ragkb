"""Тесты потоковой выдачи. Запуск: python tests/test_stream.py"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ragkb.config import Config
from ragkb.pipeline import RAGPipeline, build_index

SAMPLE_DOC = (
    "# Политика\n\n## Пароли\n\nПароль должен содержать не менее 12 символов.\n\n"
    "## Отпуск\n\nЕжегодный отпуск составляет 28 календарных дней.\n"
)


def _workspace() -> Config:
    """Крошечный корпус во временном каталоге, numpy-хранилище, без сети."""
    workdir = Path(tempfile.mkdtemp(prefix="ragkb-stream-"))
    docs = workdir / "docs"
    docs.mkdir()
    (docs / "policy.md").write_text(SAMPLE_DOC, encoding="utf-8")
    cfg = Config(docs_dir=str(docs), index_dir=str(workdir / "index"))
    cfg.store.backend = "numpy"
    cfg.history.path = str(workdir / "history.sqlite3")
    return cfg


def _pipeline() -> RAGPipeline:
    cfg = _workspace()
    build_index(cfg)
    return RAGPipeline(cfg)


def test_stream_answer_returns_hits_and_iterator():
    hits, stream = _pipeline().stream_answer("сколько дней отпуска?")
    assert hits, "поиск должен был что-то найти"
    assert not isinstance(stream, (str, list)), "второй элемент — итератор"


def test_stream_answer_yields_text():
    hits, stream = _pipeline().stream_answer("сколько дней отпуска?")
    text = "".join(stream)
    assert "28" in text, text


def test_stream_answer_without_hits_gives_empty_list():
    rag = _pipeline()
    rag.cfg.retrieval.min_score = 2.0   # выше любой косинусной близости
    hits, stream = rag.stream_answer("вопрос про то, чего в корпусе нет")
    assert hits == []
    assert "нет информации" in "".join(stream).lower()


def test_stream_answer_accepts_history():
    rag = _pipeline()
    # Экстрактивный бэкенд не обращается к сети, поэтому _condense вернёт None
    # и запрос уйдёт в исходном виде — важно, что вызов не падает.
    hits, stream = rag.stream_answer(
        "а сколько дней?", history=[("сколько дней отпуска?", "28 календарных дней")]
    )
    assert isinstance(hits, list)
    assert "".join(stream)


def test_cited_sources_works_on_streamed_text():
    rag = _pipeline()
    hits, stream = rag.stream_answer("сколько дней отпуска?")
    text = "".join(stream)
    sources = RAGPipeline._cited_sources(text, hits)
    assert isinstance(sources, list)


if __name__ == "__main__":
    failed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"  ok   {name}")
            except Exception as exc:
                failed += 1
                print(f"  FAIL {name}: {type(exc).__name__}: {exc}")
    print(f"\n{'все тесты пройдены' if not failed else f'провалов: {failed}'}")
    raise SystemExit(1 if failed else 0)
