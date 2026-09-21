"""Независимый ответ без аккаунтов и хранения переписки."""
from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable, Iterator

from ragkb.core.errors import InvalidRequest
from ragkb.core.ports import AnswerEngine

log = logging.getLogger("ragkb")


class AskService:
    def __init__(self, engine: Callable[[], AnswerEngine], resolve_model: Callable):
        self._engine = engine
        self.resolve_model = resolve_model

    def stream(self, question: str, *, model=None, top_k=None, expand=False) -> Iterator[str]:
        try:
            resolved = self.resolve_model(model)
        except ValueError as exc:
            raise InvalidRequest(str(exc)) from exc
        engine = self._engine()
        started = time.time()
        hits, tokens = engine.stream_answer(
            question, top_k=top_k, expand=expand, model=resolved
        )
        return self._generate(tokens, hits, question, resolved, started, engine)

    def _generate(
        self,
        tokens: Iterator[str],
        hits,
        question: str,
        model: str,
        started: float,
        engine: AnswerEngine,
    ) -> Iterator[str]:
        collected: list[str] = []
        warnings: list[str] = []
        truncated = False
        try:
            for piece in tokens:
                collected.append(piece)
                yield json.dumps({"type": "token", "text": piece}, ensure_ascii=False) + "\n"
        except Exception as exc:
            if collected:
                truncated = True
                warnings.append("Ответ оборвался до завершения")
            else:
                warnings.append(f"{exc} — ответ собран экстрактивно")
                fallback = engine.fallback_text(question, hits)
                collected.append(fallback)
                yield json.dumps(
                    {"type": "token", "text": fallback}, ensure_ascii=False
                ) + "\n"

        text = "".join(collected)
        sources = engine.cited_sources(text, hits)
        if not hits:
            warnings.append("Поиск не вернул ни одного релевантного фрагмента")
        if not sources and "нет информации" not in text.lower():
            warnings.append(
                "Модель не проставила ссылки на источники — ответ стоит проверить"
            )
        elapsed_sec = round(time.time() - started, 2)
        log.info(
            "ответ готов за %s с, источников %s, модель %s%s",
            elapsed_sec,
            len(sources),
            model,
            ", warnings: " + "; ".join(warnings) if warnings else "",
        )

        yield json.dumps(
            {
                "type": "done",
                "sources": sources,
                "warnings": warnings,
                "elapsed_sec": elapsed_sec,
                "model": model,
                "truncated": truncated,
            },
            ensure_ascii=False,
        ) + "\n"

