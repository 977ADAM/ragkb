"""Поток ядра: находки, токены ответа и вызовы инструмента."""
from helpers import ScriptedChatModel
from langchain_core.messages import AIMessage

from ragkb.core.answer_events import TOOL_GET_DOWNLOAD_LINK
from ragkb.core.pipeline import RagChain


def test_stream_answer_yields_tokens(indexed, monkeypatch):
    monkeypatch.setattr(
        "ragkb.core.pipeline.build_chat_model",
        lambda *_args, **_kwargs: ScriptedChatModel(responses=["28 календарных дней [1]."]),
    )
    rag = RagChain(indexed)

    hits, stream = rag.stream_answer("сколько дней отпуска?")
    text = "".join(stream)

    assert "28" in text
    assert isinstance(hits, list)


def test_stream_answer_with_query_expansion(indexed, monkeypatch):
    monkeypatch.setattr(
        "ragkb.core.pipeline.build_chat_model",
        lambda *_args, **_kwargs: ScriptedChatModel(
            responses=['{"queries": ["ежегодный оплачиваемый отпуск"]}']
        ),
    )
    rag = RagChain(indexed)

    hits, stream = rag.stream_answer("сколько дней отпуска?", expand=True)
    text = "".join(stream)

    assert isinstance(hits, list)
    assert text

async def test_stream_tool_answer_performs_the_tool_call(indexed, monkeypatch):
    """Ядро само выполняет вызов инструмента и отдаёт событие вложения."""
    document_id = "11111111-1111-4111-8111-111111111111"
    monkeypatch.setattr(
        "ragkb.core.pipeline.build_chat_model",
        lambda *_args, **_kwargs: ScriptedChatModel(
            responses=[
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": TOOL_GET_DOWNLOAD_LINK,
                            "args": {"document_id": document_id},
                            "id": "call-1",
                        }
                    ],
                ),
                AIMessage(content="Файл приложен [1]."),
            ]
        ),
    )
    rag = RagChain(indexed)
    hits = rag.search("сколько дней отпуска?")
    asked: list[str] = []

    async def resolve(candidate_id: str) -> dict:
        asked.append(candidate_id)
        return {
            "document_id": candidate_id,
            "filename": "policy.md",
            "url": f"/api/documents/{candidate_id}/download",
            "media_type": "text/markdown",
            "size": 10,
        }

    events = [
        event
        async for event in rag.stream_tool_answer(
            "Пришли policy.md",
            hits=hits,
            candidates=[
                {"document_id": document_id, "filename": "policy.md", "download_allowed": True}
            ],
            resolve_download=resolve,
        )
    ]

    assert asked == [document_id]
    assert [event.kind for event in events].count("attachment") == 1
    assert any("приложен" in str(event.value) for event in events)
