"""Сравнение режимов поиска на тестовом наборе.

Запуск: python examples/ablation.py

Показывает, что даёт каждая часть гибридной схемы. На своём корпусе стоит
прогнать то же самое — оптимальная конфигурация зависит от того, чего в
запросах больше: точных терминов или перефразировок.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ragkb.config import Config
from ragkb.evaluation import evaluate, load_cases
from ragkb.pipeline import RAGPipeline

MODES = [
    ("только BM25",        dict(use_bm25=True,  use_dense=False, use_mmr=False)),
    ("только векторы",     dict(use_bm25=False, use_dense=True,  use_mmr=False)),
    ("гибрид (RRF)",       dict(use_bm25=True,  use_dense=True,  use_mmr=False)),
    ("гибрид + MMR",       dict(use_bm25=True,  use_dense=True,  use_mmr=True)),
]


def main() -> int:
    cfg = Config.load("config.yaml")
    cases = load_cases("examples/eval_set.jsonl")

    print(f"{'режим':<18} {'Hit@1':>7} {'Hit@3':>7} {'Hit@5':>7} {'MRR':>7}")
    print("-" * 50)
    for name, overrides in MODES:
        for key, value in overrides.items():
            setattr(cfg.retrieval, key, value)
        pipeline = RAGPipeline(cfg)
        row = [name.ljust(18)]
        for k in (1, 3, 5):
            row.append(f"{evaluate(pipeline, cases, top_k=k).hit_rate:>7.1%}")
        row.append(f"{evaluate(pipeline, cases, top_k=5).mrr:>7.3f}")
        print(" ".join(row))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
