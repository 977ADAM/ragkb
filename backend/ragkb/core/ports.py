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

    def cited_sources(self, text: str, hits: list[Hit]) -> list[dict[str, Any]]: ...

    def fallback_text(self, question: str, hits: list[Hit]) -> str: ...

    def document_paths(self) -> set[str] | None: ...


class IndexEngine(Protocol):
    def stats(self) -> dict[str, Any]: ...

    def rebuild(self, allow: frozenset[str] | None = None) -> Any:
        """Переиндексация; `allow` — имена документов, принятых в корпус."""

    def manifest(self) -> dict[str, Any]: ...

    def reindex_after_delete(
        self, path: str, allow: frozenset[str] | None = None
    ) -> None: ...
