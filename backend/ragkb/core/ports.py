"""Порты ядра, которые объявляет прикладной слой, а не само ядро.

RagChain удовлетворяет AnswerEngine структурно и ничего не наследует:
прикладной слой не знает ни про LangChain, ни про хранилище векторов.
"""
from __future__ import annotations

from collections.abc import AsyncIterator, Iterator, Sequence
from typing import Any, Protocol

from ragkb.core.answer_events import AnswerEvent, DownloadResolver, ToolCandidate
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
        expand: bool = False,
        model: str | None = None,
    ) -> tuple[list[Hit], Iterator[str]]: ...

    def stream_tool_answer(
        self,
        question: str,
        *,
        hits: list[Hit],
        model: str | None = None,
        candidates: Sequence[ToolCandidate] = (),
        resolve_download: DownloadResolver | None = None,
    ) -> AsyncIterator[AnswerEvent]:
        """Ответ с инструментами: цикл «модель → вызовы → результаты → модель».

        Находки приходят снаружи: поиск и подготовка кандидатов выполняются до
        открытия потока, чтобы отказ можно было вернуть HTTP-кодом.
        """

    def cited_sources(self, text: str, hits: list[Hit]) -> list[dict[str, Any]]: ...

    def llm_available(self, model: str | None = None) -> bool:
        """Готова ли генерация: если нет, вопрос отклоняется до открытия потока."""


class IndexEngine(Protocol):
    def stats(self) -> dict[str, Any]: ...

    def probe(self) -> str:
        """«ok» или «no_index» — дешёвая проверка без сборки движка."""

    def rebuild(self, names: frozenset[str]) -> Any:
        """Переиндексация; `names` — имена документов из реестра корпуса."""

    def manifest(self) -> dict[str, Any]: ...

    def reindex_after_delete(self, path: str, names: frozenset[str]) -> None: ...
