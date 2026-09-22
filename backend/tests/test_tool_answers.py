"""Цикл ответа с инструментом: вызовы, лимиты, отказы и вложения.

Проверяется настоящий цикл «модель → вызовы → результаты → модель»: сборка
фрагментированных аргументов, один инструмент, лимиты раундов и вызовов,
контролируемые отказы вместо исключений и отмена, которую нельзя проглотить.
"""
from __future__ import annotations

import asyncio
import json

import pytest
from helpers import ScriptedChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGenerationChunk

from ragkb.core.answer_events import (
    TOOL_GET_DOWNLOAD_LINK,
    TOOL_NOT_AVAILABLE,
    AnswerEvent,
)
from ragkb.core.errors import EngineUnavailable
from ragkb.core.prompts import format_candidates
from ragkb.core.tool_answers import (
    MAX_TOOL_CALLS,
    MAX_TOOL_ROUNDS,
    TOOL_DEFINITION,
    stream_answer_with_tools,
)

DOCUMENT_ID = "11111111-1111-4111-8111-111111111111"
OTHER_ID = "22222222-2222-4222-8222-222222222222"


def _call(document_id: str = DOCUMENT_ID, call_id: str = "call-1") -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[
            {
                "name": TOOL_GET_DOWNLOAD_LINK,
                "args": {"document_id": document_id},
                "id": call_id,
            }
        ],
    )


def _attachment(document_id: str = DOCUMENT_ID) -> dict:
    return {
        "document_id": document_id,
        "filename": "spec.pdf",
        "url": f"/api/documents/{document_id}/download",
        "media_type": "application/pdf",
        "size": 10,
    }


def _candidates(*document_ids: str, allowed: bool = True) -> list[dict]:
    return [
        {"document_id": document_id, "filename": "spec.pdf", "download_allowed": allowed}
        for document_id in document_ids
    ]


def _resolver(result: dict | None = None, seen: list[str] | None = None):
    calls = seen if seen is not None else []

    async def resolve(document_id: str) -> dict:
        calls.append(document_id)
        return result if result is not None else _attachment(document_id)

    resolve.seen = calls  # type: ignore[attr-defined]
    return resolve


async def _collect(events) -> list[AnswerEvent]:
    return [event async for event in events]


def _text(events: list[AnswerEvent]) -> str:
    return "".join(str(event.value) for event in events if event.kind == "token")


# --------------------------------------------------------------- основной цикл


async def test_tool_call_becomes_attachment_and_generation_continues():
    model = ScriptedChatModel(
        responses=[_call(), AIMessage(content="Требования приложены. [1]")]
    )
    resolve = _resolver()

    events = await _collect(
        stream_answer_with_tools(
            model=model,
            messages=[HumanMessage(content="Пришли требования")],
            candidates=_candidates(DOCUMENT_ID),
            resolve_download=resolve,
        )
    )

    attachments = [event for event in events if event.kind == "attachment"]
    assert [event.value["document_id"] for event in attachments] == [DOCUMENT_ID]
    assert "приложены" in _text(events)
    assert resolve.seen == [DOCUMENT_ID]

    # Второй вызов модели получил результат инструмента с тем же идентификатором.
    tool_messages = [message for message in model.calls[1] if isinstance(message, ToolMessage)]
    assert [message.tool_call_id for message in tool_messages] == ["call-1"]
    assert "spec.pdf" in str(tool_messages[0].content)
    # Инструменты действительно дошли до модели.
    assert TOOL_GET_DOWNLOAD_LINK in json.dumps(model.bound_tools[0], ensure_ascii=False)


async def test_fragmented_arguments_are_reassembled():
    """Сервер отдаёт аргументы частями: склеивать их обязан цикл."""
    model = ScriptedChatModel(responses=[_call(), AIMessage(content="готово")])
    resolve = _resolver()

    await _collect(
        stream_answer_with_tools(
            model=model,
            messages=[HumanMessage(content="Пришли требования")],
            candidates=_candidates(DOCUMENT_ID),
            resolve_download=resolve,
        )
    )

    assert resolve.seen == [DOCUMENT_ID]


async def test_repeated_id_is_resolved_and_attached_once():
    model = ScriptedChatModel(
        responses=[
            _call(call_id="call-1"),
            _call(call_id="call-2"),
            AIMessage(content="готово"),
        ]
    )
    resolve = _resolver()

    events = await _collect(
        stream_answer_with_tools(
            model=model,
            messages=[HumanMessage(content="Пришли требования")],
            candidates=_candidates(DOCUMENT_ID),
            resolve_download=resolve,
        )
    )

    assert resolve.seen == [DOCUMENT_ID]
    assert [event.kind for event in events].count("attachment") == 1


async def test_several_calls_in_one_round():
    both = AIMessage(
        content="",
        tool_calls=[
            {"name": TOOL_GET_DOWNLOAD_LINK, "args": {"document_id": DOCUMENT_ID}, "id": "a"},
            {"name": TOOL_GET_DOWNLOAD_LINK, "args": {"document_id": OTHER_ID}, "id": "b"},
        ],
    )
    model = ScriptedChatModel(responses=[both, AIMessage(content="готово")])
    resolve = _resolver()

    events = await _collect(
        stream_answer_with_tools(
            model=model,
            messages=[HumanMessage(content="Пришли оба")],
            candidates=_candidates(DOCUMENT_ID, OTHER_ID),
            resolve_download=resolve,
        )
    )

    assert resolve.seen == [DOCUMENT_ID, OTHER_ID]
    assert [event.kind for event in events].count("attachment") == 2


async def test_plain_answer_without_tools():
    model = ScriptedChatModel(responses=[AIMessage(content="Просто ответ [1].")])

    events = await _collect(
        stream_answer_with_tools(
            model=model,
            messages=[HumanMessage(content="Сколько дней отпуска?")],
            candidates=_candidates(DOCUMENT_ID),
            resolve_download=_resolver(),
        )
    )

    assert [event.kind for event in events] == ["token", "token", "token"]
    assert len(model.calls) == 1


# ------------------------------------------------------------------- отказы


async def test_refusal_keeps_the_text_answer():
    model = ScriptedChatModel(
        responses=[_call(), AIMessage(content="Оригинал недоступен, отвечаю по фрагментам [1].")]
    )
    resolve = _resolver(result={"error": TOOL_NOT_AVAILABLE})

    events = await _collect(
        stream_answer_with_tools(
            model=model,
            messages=[HumanMessage(content="Пришли требования")],
            candidates=_candidates(DOCUMENT_ID),
            resolve_download=resolve,
        )
    )

    assert [event.kind for event in events].count("attachment") == 0
    assert any(event.kind == "warning" for event in events)
    assert "фрагментам" in _text(events)


async def test_unknown_tool_is_warned():
    model = ScriptedChatModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[{"name": "delete_everything", "args": {}, "id": "x"}],
            ),
            AIMessage(content="готово"),
        ]
    )
    resolve = _resolver()

    events = await _collect(
        stream_answer_with_tools(
            model=model,
            messages=[HumanMessage(content="Пришли требования")],
            candidates=_candidates(DOCUMENT_ID),
            resolve_download=resolve,
        )
    )

    assert resolve.seen == []
    assert any("неизвестный инструмент" in str(event.value).lower() for event in events)
    tool_messages = [message for message in model.calls[1] if isinstance(message, ToolMessage)]
    assert TOOL_NOT_AVAILABLE in str(tool_messages[0].content)


async def test_broken_arguments_are_warned_without_calling_the_resolver():
    """Сервер может прислать аргументы, из которых не собирается JSON."""

    class BrokenArguments(ScriptedChatModel):
        def _stream(self, messages, stop=None, run_manager=None, **kwargs):  # type: ignore[no-untyped-def]
            self.calls.append(list(messages))
            if len(self.calls) > 1:
                yield ChatGenerationChunk(message=AIMessageChunk(content="готово"))
                return
            for position, piece in enumerate(('{"document_id": ', "не json вовсе")):
                yield ChatGenerationChunk(
                    message=AIMessageChunk(
                        content="",
                        tool_call_chunks=[
                            {
                                # Имя и идентификатор приходят только с первой
                                # частью — как у настоящего сервера.
                                "name": TOOL_GET_DOWNLOAD_LINK if position == 0 else None,
                                "args": piece,
                                "id": "bad" if position == 0 else None,
                                "index": 0,
                                "type": "tool_call_chunk",
                            }
                        ],
                    )
                )

    model = BrokenArguments()
    resolve = _resolver()

    events = await _collect(
        stream_answer_with_tools(
            model=model,
            messages=[HumanMessage(content="Пришли требования")],
            candidates=_candidates(DOCUMENT_ID),
            resolve_download=resolve,
        )
    )

    assert resolve.seen == []
    assert any("аргумент" in str(event.value).lower() for event in events)
    assert "готово" in _text(events)


async def test_id_outside_candidates_is_refused():
    model = ScriptedChatModel(responses=[_call(OTHER_ID), AIMessage(content="готово")])
    resolve = _resolver()

    events = await _collect(
        stream_answer_with_tools(
            model=model,
            messages=[HumanMessage(content="Пришли требования")],
            candidates=_candidates(DOCUMENT_ID),
            resolve_download=resolve,
        )
    )

    assert resolve.seen == []
    assert any(event.kind == "warning" for event in events)
    tool_messages = [message for message in model.calls[1] if isinstance(message, ToolMessage)]
    assert TOOL_NOT_AVAILABLE in str(tool_messages[0].content)


# ------------------------------------------------------------------- лимиты


async def test_round_limit_finishes_without_tools():
    model = ScriptedChatModel(responses=[_call()])
    resolve = _resolver()

    events = await _collect(
        stream_answer_with_tools(
            model=model,
            messages=[HumanMessage(content="Пришли требования")],
            candidates=_candidates(DOCUMENT_ID),
            resolve_download=resolve,
        )
    )

    assert any("предел" in str(event.value).lower() for event in events)
    # Раундов с инструментами — не больше предела, затем проход без инструментов.
    assert len(model.calls) == MAX_TOOL_ROUNDS + 1
    assert model.bound_tools[-1] is None
    # Повторный идентификатор не исполняется заново: вложение одно.
    assert resolve.seen == [DOCUMENT_ID]
    assert [event.kind for event in events].count("attachment") == 1


async def test_call_limit_stops_the_loop():
    many = AIMessage(
        content="",
        tool_calls=[
            {
                "name": TOOL_GET_DOWNLOAD_LINK,
                "args": {"document_id": f"{index:08d}-1111-4111-8111-111111111111"},
                "id": f"call-{index}",
            }
            for index in range(4)
        ],
    )
    model = ScriptedChatModel(responses=[many])
    resolve = _resolver()
    candidates = _candidates(*[f"{index:08d}-1111-4111-8111-111111111111" for index in range(8)])

    events = await _collect(
        stream_answer_with_tools(
            model=model,
            messages=[HumanMessage(content="Пришли всё")],
            candidates=candidates,
            resolve_download=resolve,
        )
    )

    assert len(resolve.seen) <= MAX_TOOL_CALLS
    assert any("предел" in str(event.value).lower() for event in events)
    assert model.bound_tools[-1] is None


# ------------------------------------------------------- поддержка и отмена


async def test_model_without_tool_support_is_an_explicit_error():
    class NoTools(ScriptedChatModel):
        """Модель без поддержки инструментов: как базовая реализация LangChain."""

        def bind_tools(self, tools, **kwargs):  # type: ignore[no-untyped-def]
            raise NotImplementedError

    model = NoTools(responses=[AIMessage(content="текст")])

    with pytest.raises(EngineUnavailable) as exc:
        await _collect(
            stream_answer_with_tools(
                model=model,
                messages=[HumanMessage(content="Пришли требования")],
                candidates=_candidates(DOCUMENT_ID),
                resolve_download=_resolver(),
            )
        )

    assert "инструмент" in exc.value.detail.lower()


async def test_cancellation_is_not_swallowed():
    class Cancelling(ScriptedChatModel):
        def _stream(self, messages, stop=None, run_manager=None, **kwargs):  # type: ignore[no-untyped-def]
            self.calls.append(list(messages))
            yield ChatGenerationChunk(message=AIMessageChunk(content="часть "))
            raise asyncio.CancelledError

    model = Cancelling()

    with pytest.raises(asyncio.CancelledError):
        await _collect(
            stream_answer_with_tools(
                model=model,
                messages=[HumanMessage(content="Пришли требования")],
                candidates=_candidates(DOCUMENT_ID),
                resolve_download=_resolver(),
            )
        )


# ------------------------------------------------------------ схема и промпт


def test_tool_schema_is_strict_and_requires_document_id():
    function = TOOL_DEFINITION["function"]

    assert function["name"] == TOOL_GET_DOWNLOAD_LINK
    assert function["parameters"]["required"] == ["document_id"]
    assert function["parameters"]["additionalProperties"] is False
    assert function["parameters"]["properties"]["document_id"]["type"] == "string"


def test_prompt_lists_candidates_with_availability():
    text = format_candidates(
        [
            {"document_id": DOCUMENT_ID, "filename": "AdSmart Multi.pdf", "download_allowed": True},
            {"document_id": OTHER_ID, "filename": "faq.docx", "download_allowed": False},
        ]
    )

    assert DOCUMENT_ID in text and "AdSmart Multi.pdf" in text
    assert OTHER_ID in text and "faq.docx" in text
    assert "недоступ" in text.lower()
    assert format_candidates([])
