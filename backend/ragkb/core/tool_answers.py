"""Цикл ответа с инструментом: модель → вызовы → результаты → модель.

`StrOutputParser` между моделью и обработчиком вызовов не стоит: он вернул бы
только текст и потерял бы `tool_calls`. Поэтому сообщения модели читаются
потоком как есть, фрагменты складываются до полных аргументов, и только после
этого вызывается обработчик.

Цикл живёт внутри одного вопроса: сообщения инструментов и переписка между
запросами не сохраняются — каждый вопрос независим.
"""
from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator, Sequence
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage, ToolMessage

from .answer_events import (
    TOOL_GET_DOWNLOAD_LINK,
    TOOL_NOT_AVAILABLE,
    AnswerEvent,
    DownloadResolver,
    ToolCandidate,
)
from .errors import EngineUnavailable

log = logging.getLogger("ragkb")

# Пределы одного вопроса: раунды с инструментами и вызовы суммарно.
MAX_TOOL_ROUNDS = 3
MAX_TOOL_CALLS = 8

TOOL_DEFINITION: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": TOOL_GET_DOWNLOAD_LINK,
        "description": (
            "Прикладывает оригинал зарегистрированного документа корпуса для "
            "скачивания. Вызывать с идентификатором из списка доступных оригиналов."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "document_id": {
                    "type": "string",
                    "description": "Идентификатор документа из списка оригиналов",
                }
            },
            "required": ["document_id"],
            "additionalProperties": False,
        },
    },
}

_ROUND_LIMIT_WARNING = (
    "Достигнут предел обращений к инструменту — отвечаю без него"
)
_CALL_LIMIT_WARNING = "Достигнут предел вызовов инструмента — отвечаю без него"


async def stream_answer_with_tools(
    *,
    model: BaseChatModel,
    messages: Sequence[BaseMessage],
    candidates: Sequence[ToolCandidate] = (),
    resolve_download: DownloadResolver | None = None,
) -> AsyncIterator[AnswerEvent]:
    """Отдаёт события ответа, выполняя вызовы инструмента по ходу генерации.

    Текст модели уходит токенами, аргументы и служебные сообщения инструмента —
    нет. Успешное вложение отдаётся событием `attachment`, отказ — только
    предупреждением: он не должен обрывать полезный ответ.
    """
    bound = _bind_tools(model)
    conversation: list[BaseMessage] = list(messages)
    resolved: dict[str, dict[str, Any]] = {}
    allowed = {candidate["document_id"] for candidate in candidates}
    calls = 0
    rounds = 0

    while True:
        if rounds >= MAX_TOOL_ROUNDS:
            yield AnswerEvent("warning", _ROUND_LIMIT_WARNING)
            async for event in _plain_answer(model, conversation):
                yield event
            return
        rounds += 1

        answer = None
        async for chunk in bound.astream(conversation):
            answer = chunk if answer is None else answer + chunk
            text = _chunk_text(chunk)
            if text:
                yield AnswerEvent("token", text)

        tool_calls = list(getattr(answer, "tool_calls", []) or [])
        if not tool_calls:
            return
        conversation.append(
            AIMessage(content=_message_text(answer), tool_calls=tool_calls)
        )

        for call in tool_calls:
            calls += 1
            if calls > MAX_TOOL_CALLS:
                yield AnswerEvent("warning", _CALL_LIMIT_WARNING)
                conversation.append(
                    ToolMessage(
                        content=json.dumps({"error": "limit"}, ensure_ascii=False),
                        tool_call_id=str(call.get("id") or ""),
                    )
                )
                async for event in _plain_answer(model, conversation):
                    yield event
                return

            result, event = await _run_tool_call(call, allowed, resolved, resolve_download)
            if event is not None:
                yield event
            conversation.append(
                ToolMessage(
                    content=json.dumps(result, ensure_ascii=False),
                    tool_call_id=str(call.get("id") or ""),
                )
            )


def _bind_tools(model: BaseChatModel) -> BaseChatModel:
    """Связывает модель с единственным инструментом.

    Неподдерживаемый tool calling — явная ошибка: подменять вызовы разбором
    ссылок в тексте нельзя, иначе модель «выдавала» бы файлы словами, а сервер
    не смог бы ничего проверить.
    """
    try:
        return model.bind_tools([TOOL_DEFINITION])
    except (AttributeError, NotImplementedError, TypeError) as exc:
        raise EngineUnavailable(
            "Модель не поддерживает вызов инструментов: выберите модель с "
            "поддержкой tool calling"
        ) from exc


async def _plain_answer(
    model: BaseChatModel, conversation: list[BaseMessage]
) -> AsyncIterator[AnswerEvent]:
    """Ответ без инструментов: текст всё равно должен прозвучать."""
    async for chunk in model.astream(conversation):
        text = _chunk_text(chunk)
        if text:
            yield AnswerEvent("token", text)


async def _run_tool_call(
    call: dict[str, Any],
    allowed: set[str],
    resolved: dict[str, dict[str, Any]],
    resolve_download: DownloadResolver | None,
) -> tuple[dict[str, Any], AnswerEvent | None]:
    """Выполняет один вызов и возвращает результат для модели и событие."""
    name = str(call.get("name") or "")
    if name != TOOL_GET_DOWNLOAD_LINK:
        return (
            {"error": TOOL_NOT_AVAILABLE},
            AnswerEvent("warning", f"Модель вызвала неизвестный инструмент: {name or '—'}"),
        )

    document_id, complaint = _document_id(call.get("args"))
    if complaint is not None:
        return {"error": TOOL_NOT_AVAILABLE}, AnswerEvent("warning", complaint)
    if document_id not in allowed:
        return (
            {"error": TOOL_NOT_AVAILABLE},
            AnswerEvent("warning", "Модель запросила документ, которого не было в списке"),
        )
    if document_id in resolved:
        # Успешный вызов повторно не исполняется: вложение должно быть одно.
        return resolved[document_id], None
    if resolve_download is None:
        return (
            {"error": TOOL_NOT_AVAILABLE},
            AnswerEvent("warning", "Оригинал документа недоступен"),
        )

    result = await resolve_download(document_id)
    if "error" in result:
        return result, AnswerEvent("warning", "Оригинал документа недоступен")
    resolved[document_id] = result
    return result, AnswerEvent("attachment", result)


def _document_id(args: Any) -> tuple[str, str | None]:
    """Достаёт идентификатор из аргументов вызова.

    Аргументы приходят от модели и могут быть невалидным JSON или вовсе не
    объектом: это не повод обрывать ответ, но и не повод вызывать инструмент.
    """
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except ValueError:
            return "", "Модель передала невалидные аргументы инструмента"
    if not isinstance(args, dict):
        return "", "Модель передала невалидные аргументы инструмента"
    document_id = args.get("document_id")
    if not isinstance(document_id, str) or not document_id.strip():
        return "", "Модель передала невалидные аргументы инструмента: нет document_id"
    return document_id.strip(), None


def _chunk_text(chunk: AIMessageChunk) -> str:
    """Текст порции: у части моделей содержимое приходит блоками."""
    content = chunk.content
    if isinstance(content, str):
        return content
    parts: list[str] = []
    for block in content or []:
        if isinstance(block, dict) and block.get("type") == "text":
            parts.append(str(block.get("text") or ""))
    return "".join(parts)


def _message_text(message: AIMessageChunk | None) -> str:
    return _chunk_text(message) if message is not None else ""
