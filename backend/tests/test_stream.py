"""Поток ядра: находки и токены ответа."""
from helpers import ScriptedChatModel

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
