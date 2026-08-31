"""Порты ядра, которые объявляет прикладной слой, а не само ядро.

RAGPipeline удовлетворяет AnswerEngine структурно и ничего не наследует.
"""
from __future__ import annotations

from collections.abc import Iterator
from typing import Any, Protocol

from ragkb.core.retrieval import Hit


class AnswerEngine(Protocol):
    def search(
        self, question: str, top_k: int | None = None, expand: bool = False
    ) -> list[Hit]: ...

    def stream_answer(
        self,
        question: str,
        *,
        top_k: int | None = None,
        history: list[tuple[str, str]] | None = None,
        expand: bool = False,
        model: str | None = None,
    ) -> tuple[list[Hit], Iterator[str]]: ...

    def stats(self) -> dict[str, Any]: ...
