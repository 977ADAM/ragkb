"""Проверка корректности ответов, а не только поиска.

ragkb eval меряет retrieval: попал ли нужный чанк в top-k. Но чанк может попасть
в контекст, а модель всё равно ответит неверно — этот класс ошибок eval не видит.
Здесь проверяется сам текст ответа: содержит ли он ожидаемый факт и проставлена ли
ссылка на источник.

Запуск:
    python examples/answer_check.py                      # модель из config.yaml
    python examples/answer_check.py qwen2.5:7b-instruct  # переопределить модель
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ragkb.core.config import Config
from ragkb.core.evaluation import load_cases
from ragkb.core.pipeline import RAGPipeline

DATASET = "examples/eval_set.jsonl"


def normalize(text: str) -> str:
    """Приводит текст к виду, в котором «300 000 руб.» и «300000 рублей» совпадают."""
    text = text.lower().replace(" ", " ").replace(" ", " ").replace("ё", "е")
    text = re.sub(r"\s+", " ", text)
    # Пробелы внутри числовых групп — разделители разрядов, а не границы слов.
    text = re.sub(r"(?<=\d) (?=\d)", "", text)
    return text.replace(" %", "%")


def matches(expected: str, answer: str) -> bool:
    """Совпадение по смыслу, а не буквальное.

    expected в eval_set сформулировано под поиск — это маркер внутри чанка. Модель
    тот же факт переформулирует («7 рублей за километр» → «составляет 7 рублей»),
    поэтому буквальное вхождение даёт ложные провалы. Сверяем по числам, а при их
    отсутствии — по доле совпавших значимых слов.
    """
    exp, ans = normalize(expected), normalize(answer)
    if exp in ans:
        return True
    numbers = re.findall(r"\d+(?:[.,]\d+)?", exp)
    if numbers:
        return all(re.search(rf"(?<!\d){re.escape(n)}(?!\d)", ans) for n in numbers)
    words = re.findall(r"[а-яa-z]{4,}", exp)
    if not words:
        return False
    return sum(w[:5] in ans for w in words) / len(words) >= 0.6


def main() -> int:
    cfg = Config.load("config.yaml")
    if len(sys.argv) > 1:
        cfg.llm.backend, cfg.llm.model = "ollama", sys.argv[1]

    rag = RAGPipeline(cfg)
    cases = load_cases(DATASET)
    print(f"Модель: {rag.llm.name}   вопросов: {len(cases)}\n")

    correct = cited = 0
    failures: list[tuple[str, str, str]] = []
    total_time = 0.0

    for i, case in enumerate(cases, start=1):
        answer = rag.ask(case.question)
        total_time += answer.elapsed
        ok = any(matches(phrase, answer.text) for phrase in case.expected)
        correct += ok
        cited += bool(answer.used_sources)
        print(f"  {'ok  ' if ok else 'ПЛОХО'} [{i:2}/{len(cases)}] {case.question}")
        if not ok:
            failures.append((case.question, case.expected[0], answer.text))

    n = len(cases)
    print(
        f"\nФакт в ответе:   {correct}/{n} ({correct / n:.1%})"
        f"\nСо ссылкой [N]:  {cited}/{n} ({cited / n:.1%})"
        f"\nСреднее время:   {total_time / n:.1f} с"
    )
    if failures:
        print("\nРазбор ошибок:")
        for question, expected, got in failures:
            print(f"\n  ? {question}")
            print(f"    ожидалось: {expected}")
            print(f"    ответ:     {got[:300]}")
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
