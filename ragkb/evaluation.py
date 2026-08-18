"""Оценка качества поиска.

RAG ломается почти всегда в retrieval, а не в генерации: если нужного чанка
нет в top-k, никакая модель не спасёт. Поэтому базовый набор метрик — по
поиску, и мерить их надо на своём корпусе, а не на публичных бенчмарках.

Формат тестового набора (JSONL):
    {"question": "...", "expected": ["фраза-маркер", "..."], "doc": "regламент.pdf"}

expected — подстроки, которые обязаны встретиться в правильном чанке;
doc — необязательное ограничение на имя файла-источника.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .pipeline import RAGPipeline


@dataclass
class EvalCase:
    question: str
    expected: list[str]
    doc: str | None = None


@dataclass
class EvalResult:
    n: int
    hit_rate: float          # доля вопросов, где нужный чанк попал в top-k
    mrr: float               # средний обратный ранг первого правильного чанка
    precision_at_k: float
    failures: list[dict[str, Any]]

    def summary(self) -> str:
        return (
            f"Вопросов: {self.n}\n"
            f"Hit@k:     {self.hit_rate:.1%}\n"
            f"MRR:       {self.mrr:.3f}\n"
            f"Precision: {self.precision_at_k:.1%}\n"
            f"Провалов:  {len(self.failures)}"
        )


def load_cases(path: str | Path) -> list[EvalCase]:
    cases = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        data = json.loads(line)
        cases.append(
            EvalCase(
                question=data["question"],
                expected=data.get("expected", []),
                doc=data.get("doc"),
            )
        )
    return cases


def evaluate(pipeline: RAGPipeline, cases: list[EvalCase], top_k: int = 5) -> EvalResult:
    hits_count = 0
    reciprocal_ranks: list[float] = []
    precisions: list[float] = []
    failures: list[dict[str, Any]] = []

    for case in cases:
        results = pipeline.search(case.question, top_k=top_k)
        matched_ranks = [
            rank for rank, hit in enumerate(results, start=1) if _matches(hit, case)
        ]
        if matched_ranks:
            hits_count += 1
            reciprocal_ranks.append(1.0 / matched_ranks[0])
        else:
            reciprocal_ranks.append(0.0)
            failures.append(
                {
                    "question": case.question,
                    "expected": case.expected,
                    "got": [h.chunk.citation() for h in results],
                }
            )
        precisions.append(len(matched_ranks) / max(1, len(results)))

    n = max(1, len(cases))
    return EvalResult(
        n=len(cases),
        hit_rate=hits_count / n,
        mrr=sum(reciprocal_ranks) / n,
        precision_at_k=sum(precisions) / n,
        failures=failures,
    )


def _matches(hit, case: EvalCase) -> bool:
    if case.doc and case.doc.lower() not in hit.chunk.source.lower():
        return False
    text = hit.chunk.text.lower()
    return any(phrase.lower() in text for phrase in case.expected)
