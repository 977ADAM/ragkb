"""Независимый ответ без аккаунтов и хранения переписки."""
from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any

from ragkb.core.answer_events import AnswerEvent
from ragkb.core.errors import EngineUnavailable, InvalidRequest
from ragkb.core.ports import AnswerEngine
from ragkb.domain.ports import DocumentRegistry
from ragkb.services.download_candidates import download_resolver, prepare_candidates
from ragkb.services.downloads import DownloadsService

log = logging.getLogger("ragkb")


class AskService:
    def __init__(
        self,
        engine: Callable[[], AnswerEngine],
        resolve_model: Callable,
        registry: DocumentRegistry | None = None,
        docs_dir: str | Path | None = None,
    ) -> None:
        self._engine = engine
        self.resolve_model = resolve_model
        self._registry = registry
        self._docs_dir = Path(docs_dir) if docs_dir is not None else None

    async def stream(
        self, question: str, *, model=None, top_k=None, expand=False
    ) -> AsyncIterator[str]:
        """Готовит ответ и возвращает поток строк NDJSON.

        Это корутина, а не генератор: подготовка — выбор модели, проверка
        готовности генерации, поиск и набор кандидатов — выполняется до
        открытия потока. Поэтому отказ ещё можно вернуть HTTP-кодом (400/503),
        а не пустым ответом с кодом 200.
        """
        try:
            resolved = self.resolve_model(model)
        except ValueError as exc:
            raise InvalidRequest(str(exc)) from exc
        engine = self._engine()
        if not engine.llm_available(resolved):
            raise EngineUnavailable(
                "Генерация недоступна: задайте адрес и модель LLM "
                "(RAGKB_LLM_URL, RAGKB_LLM_MODEL) и перезапустите сервис"
            )
        started = time.time()
        # Поиск синхронный и тяжёлый: уводим его с цикла событий, иначе на
        # время поиска перестают отвечать остальные запросы.
        hits = await asyncio.to_thread(engine.search, question, top_k=top_k, expand=expand)
        # Без реестра кандидатов нет — обычный ответ при этом работает.
        candidates = []
        if self._docs_dir is not None:
            candidates = await prepare_candidates(question, hits, self._registry, self._docs_dir)
        resolve_download = None
        if candidates and self._docs_dir is not None:
            resolve_download = download_resolver(
                DownloadsService(self._docs_dir, self._registry), candidates
            )
        events = engine.stream_tool_answer(
            question,
            hits=hits,
            model=resolved,
            candidates=candidates,
            resolve_download=resolve_download,
        )
        return self._generate(events, hits, resolved, started, engine)

    async def _generate(
        self,
        events: AsyncIterator[AnswerEvent],
        hits,
        model: str,
        started: float,
        engine: AnswerEngine,
    ) -> AsyncIterator[str]:
        collected: list[str] = []
        attachments: list[dict[str, Any]] = []
        warnings: list[str] = []
        truncated = False
        failure = ""
        try:
            async for event in events:
                if event.kind == "token":
                    collected.append(str(event.value))
                    yield _line({"type": "token", "text": event.value})
                elif event.kind == "attachment":
                    # Вложения копятся на сервере: отдельными строками потока
                    # они не идут, их место — в завершающем событии.
                    attachments.append(dict(event.value))
                elif event.kind == "warning":
                    warnings.append(str(event.value))
        except asyncio.CancelledError:
            # Отмена клиента — не сбой генерации: её нельзя выдать за
            # предупреждение и продолжить работу.
            raise
        except Exception as exc:
            # Поток уже открыт: заменить ответ HTTP-ошибкой нельзя, поэтому
            # сообщаем причину предупреждением и честно завершаем поток.
            # Уже полученные вложения при этом сохраняются.
            if collected or attachments:
                truncated = True
                warnings.append("Ответ оборвался до завершения")
            else:
                failure = f"Модель не ответила: {exc}"

        text = "".join(collected)
        sources = engine.cited_sources(text, hits)
        if failure:
            warnings.append(failure)
        if not hits:
            warnings.append("Поиск не вернул ни одного релевантного фрагмента")
        if not sources and "нет информации" not in text.lower():
            warnings.append(
                "Модель не проставила ссылки на источники — ответ стоит проверить"
            )
        elapsed_sec = round(time.time() - started, 2)
        log.info(
            "ответ готов за %s с, источников %s, вложений %s, модель %s%s",
            elapsed_sec,
            len(sources),
            len(attachments),
            model,
            ", warnings: " + "; ".join(warnings) if warnings else "",
        )

        yield _line(
            {
                "type": "done",
                "sources": sources,
                "warnings": warnings,
                "elapsed_sec": elapsed_sec,
                "model": model,
                "truncated": truncated,
                "attachments": attachments,
            }
        )


def _line(payload: dict[str, Any]) -> str:
    """Строка NDJSON: несериализуемые значения приводим к строке.

    Ядро отдаёт идентификаторы документа строками, но схема обещает UUID —
    `default=str` не даёт потоку упасть, если значение придёт другим типом.
    """
    return json.dumps(payload, ensure_ascii=False, default=str) + "\n"
