"""Тесты выбора модели. Запуск: python tests/test_models.py"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ragkb.config import Config, LLMConfig
from ragkb.models import available_models, resolve_model


def _cfg() -> LLMConfig:
    return LLMConfig(
        model="qwen2.5:7b-instruct",
        available=[
            {"name": "qwen2.5:7b-instruct", "title": "Быстрая"},
            {"name": "qwen2.5:14b-instruct", "title": "Точная"},
        ],
    )


def test_available_models_marks_default():
    items = available_models(_cfg())
    assert [i["name"] for i in items] == ["qwen2.5:7b-instruct", "qwen2.5:14b-instruct"]
    assert items[0]["default"] is True
    assert items[1]["default"] is False


def test_available_models_without_list_returns_current():
    items = available_models(LLMConfig(model="что-то:latest"))
    assert len(items) == 1
    assert items[0]["name"] == "что-то:latest"
    assert items[0]["default"] is True


def test_available_models_fills_missing_title():
    items = available_models(LLMConfig(model="a", available=[{"name": "a"}]))
    assert items[0]["title"] == "a"


def test_resolve_model_returns_default_when_not_requested():
    assert resolve_model(_cfg(), None) == "qwen2.5:7b-instruct"
    assert resolve_model(_cfg(), "") == "qwen2.5:7b-instruct"


def test_resolve_model_accepts_allowed():
    assert resolve_model(_cfg(), "qwen2.5:14b-instruct") == "qwen2.5:14b-instruct"


def test_resolve_model_rejects_unknown():
    try:
        resolve_model(_cfg(), "злая:модель")
    except ValueError as exc:
        assert "злая:модель" in str(exc)
        return
    raise AssertionError("ожидался отказ для модели вне списка")


def test_resolve_model_without_list_rejects_anything_but_current():
    cfg = LLMConfig(model="только-эта")
    assert resolve_model(cfg, "только-эта") == "только-эта"
    try:
        resolve_model(cfg, "другая")
    except ValueError:
        return
    raise AssertionError("при пустом списке допустима только текущая модель")


def test_config_reads_available_from_dict():
    cfg = Config.from_dict({"llm": {"model": "a", "available": [{"name": "a", "title": "А"}]}})
    assert cfg.llm.available == [{"name": "a", "title": "А"}]


# ------------------------------------------------- модель на запрос

import tempfile

from ragkb.pipeline import RAGPipeline, build_index

SAMPLE_DOC = (
    "# Политика\n\n## Отпуск\n\nЕжегодный отпуск составляет 28 календарных дней.\n"
)


def _pipeline() -> RAGPipeline:
    workdir = Path(tempfile.mkdtemp(prefix="ragkb-models-"))
    docs = workdir / "docs"
    docs.mkdir()
    (docs / "policy.md").write_text(SAMPLE_DOC, encoding="utf-8")
    cfg = Config(docs_dir=str(docs), index_dir=str(workdir / "index"))
    cfg.store.backend = "numpy"
    cfg.history.path = str(workdir / "history.sqlite3")
    build_index(cfg)
    return RAGPipeline(cfg)


def test_llm_for_returns_same_object_without_override():
    rag = _pipeline()
    assert rag._llm_for(None) is rag.llm
    assert rag._llm_for(rag.cfg.llm.model) is rag.llm


def test_llm_for_builds_new_llm_for_other_model():
    rag = _pipeline()
    # Экстрактивный бэкенд всегда зовётся «extractive» независимо от модели,
    # поэтому имя модели видно только на бэкенде, который его включает.
    # В сеть это не ходит: конструктор OllamaLLM лишь запоминает настройки.
    rag.cfg.llm.backend = "ollama"
    other = rag._llm_for("другая-модель")
    assert other is not rag.llm
    assert "другая-модель" in other.name


def test_llm_for_keeps_backend_and_settings():
    rag = _pipeline()
    rag.cfg.llm.temperature = 0.7
    other = rag._llm_for("другая-модель")
    assert other.cfg.temperature == 0.7
    assert other.cfg.backend == rag.cfg.llm.backend


def test_ask_records_used_model():
    rag = _pipeline()
    answer = rag.ask("сколько дней отпуска?")
    assert answer.llm_backend == rag.llm.name


def test_stream_answer_accepts_model():
    rag = _pipeline()
    hits, stream = rag.stream_answer("сколько дней отпуска?", model=None)
    assert isinstance(hits, list)
    assert "".join(stream)


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
