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
