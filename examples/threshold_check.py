"""Пороговые вопросы вида «можно ли мне».

Здесь ответ требует не извлечения факта, а сравнения числа из вопроса с порогом
из документа. Автоматически такое не размечается — скрипт печатает ответы рядом
с эталонным вердиктом, вердикт выносит человек.

Запуск: python examples/threshold_check.py [модель]
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ragkb.config import Config
from ragkb.pipeline import RAGPipeline

DATASET = "examples/threshold_cases.jsonl"


def main() -> int:
    cfg = Config.load("config.yaml")
    if len(sys.argv) > 1:
        cfg.llm.backend, cfg.llm.model = "ollama", sys.argv[1]
    rag = RAGPipeline(cfg)
    cases = [json.loads(l) for l in Path(DATASET).read_text(encoding="utf-8").splitlines() if l.strip()]
    print(f"Модель: {rag.llm.name}   случаев: {len(cases)}\n")
    for i, case in enumerate(cases, start=1):
        answer = rag.ask(case["question"])
        print(f"══ [{i}] {case['question']}")
        print(f"   эталон: {case['verdict'].upper()} — {case['why']}")
        print(f"   ответ:  {answer.text}")
        print(f"   ({answer.elapsed:.1f} с)\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
