"""Поток ядра."""
from ragkb.core.pipeline import RAGPipeline


def test_stream_answer_expand_accepted(indexed):
    rag = RAGPipeline(indexed)
    hits, stream = rag.stream_answer("сколько дней отпуска?", expand=True)
    assert "".join(stream)
    assert isinstance(hits, list)
