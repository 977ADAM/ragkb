"""Тесты потоковой выдачи. Запуск: python tests/test_stream.py"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ragkb.config import Config
from ragkb.pipeline import RAGPipeline, build_index

SAMPLE_DOC = (
    "# Политика\n\n## Пароли\n\nПароль должен содержать не менее 12 символов.\n\n"
    "## Отпуск\n\nЕжегодный отпуск составляет 28 календарных дней.\n"
)


def _workspace() -> Config:
    """Крошечный корпус во временном каталоге, numpy-хранилище, без сети."""
    workdir = Path(tempfile.mkdtemp(prefix="ragkb-stream-"))
    docs = workdir / "docs"
    docs.mkdir()
    (docs / "policy.md").write_text(SAMPLE_DOC, encoding="utf-8")
    cfg = Config(docs_dir=str(docs), index_dir=str(workdir / "index"))
    cfg.store.backend = "numpy"
    cfg.history.path = str(workdir / "history.sqlite3")
    return cfg


def _pipeline() -> RAGPipeline:
    cfg = _workspace()
    build_index(cfg)
    return RAGPipeline(cfg)


def test_stream_answer_returns_hits_and_iterator():
    hits, stream = _pipeline().stream_answer("сколько дней отпуска?")
    assert hits, "поиск должен был что-то найти"
    assert not isinstance(stream, (str, list)), "второй элемент — итератор"


def test_stream_answer_yields_text():
    hits, stream = _pipeline().stream_answer("сколько дней отпуска?")
    text = "".join(stream)
    assert "28" in text, text


def test_stream_answer_without_hits_gives_empty_list():
    rag = _pipeline()
    rag.cfg.retrieval.min_score = 2.0   # выше любой косинусной близости
    hits, stream = rag.stream_answer("вопрос про то, чего в корпусе нет")
    assert hits == []
    assert "нет информации" in "".join(stream).lower()


def test_stream_answer_accepts_history():
    rag = _pipeline()
    # Экстрактивный бэкенд не обращается к сети, поэтому _condense вернёт None
    # и запрос уйдёт в исходном виде — важно, что вызов не падает.
    hits, stream = rag.stream_answer(
        "а сколько дней?", history=[("сколько дней отпуска?", "28 календарных дней")]
    )
    assert isinstance(hits, list)
    assert "".join(stream)


def test_cited_sources_works_on_streamed_text():
    rag = _pipeline()
    hits, stream = rag.stream_answer("сколько дней отпуска?")
    text = "".join(stream)
    sources = RAGPipeline._cited_sources(text, hits)
    assert isinstance(sources, list)


# ------------------------------------------------------- эндпоинт /ask/stream

import json


def _client(cfg: Config | None = None):
    from fastapi.testclient import TestClient

    from ragkb.api import create_app

    cfg = cfg or _workspace()
    cfg.auth.mode = "disabled"
    return TestClient(create_app(cfg), raise_server_exceptions=False)


def _events(response) -> list[dict]:
    """Разбирает тело NDJSON в список событий."""
    return [json.loads(line) for line in response.text.splitlines() if line.strip()]


def _indexed_client():
    """Клиент поверх построенного индекса — поток дойдёт до конца."""
    cfg = _workspace()
    build_index(cfg)
    return _client(cfg), cfg


def test_stream_returns_ndjson():
    client, _ = _indexed_client()
    resp = client.post("/ask/stream", json={"question": "сколько дней отпуска?"})
    assert resp.status_code == 200
    assert "ndjson" in resp.headers["content-type"]


def test_stream_last_event_is_done():
    client, _ = _indexed_client()
    events = _events(client.post("/ask/stream", json={"question": "сколько дней отпуска?"}))
    assert events, "поток пуст"
    assert events[-1]["type"] == "done", events[-1]
    assert any(e["type"] == "token" for e in events)


def test_done_event_carries_conversation_and_sources():
    client, _ = _indexed_client()
    done = _events(client.post("/ask/stream", json={"question": "сколько дней отпуска?"}))[-1]
    assert done["conversation_id"]
    assert isinstance(done["sources"], list)
    assert isinstance(done["warnings"], list)
    assert isinstance(done["elapsed_sec"], (int, float))


def test_stream_writes_both_messages_to_history():
    from ragkb.history import HistoryStore

    client, cfg = _indexed_client()
    done = _events(client.post("/ask/stream", json={"question": "сколько дней отпуска?"}))[-1]
    messages = HistoryStore(cfg.history.path).get_messages(done["conversation_id"], "anonymous")
    assert [m.role for m in messages] == ["user", "assistant"]
    assert messages[0].text == "сколько дней отпуска?"
    assert messages[1].text


def test_stream_continues_existing_conversation():
    client, _ = _indexed_client()
    first = _events(client.post("/ask/stream", json={"question": "сколько дней отпуска?"}))[-1]
    second = _events(client.post(
        "/ask/stream",
        json={"question": "а какой длины пароль?", "conversation_id": first["conversation_id"]},
    ))[-1]
    assert second["conversation_id"] == first["conversation_id"]


def test_stream_with_foreign_conversation_gives_404():
    from ragkb.history import HistoryStore

    client, cfg = _indexed_client()
    foreign = HistoryStore(cfg.history.path).create_conversation("petrov", "чужой")
    resp = client.post(
        "/ask/stream", json={"question": "тест", "conversation_id": foreign}
    )
    assert resp.status_code == 404, resp.status_code


def test_stream_without_index_does_not_start():
    """Индекса нет — отказ приходит кодом ответа, поток не начинается."""
    cfg = _workspace()          # build_index намеренно не вызываем
    resp = _client(cfg).post("/ask/stream", json={"question": "тест"})
    assert resp.status_code == 503, resp.status_code


def test_failed_stream_leaves_no_conversation():
    from ragkb.history import HistoryStore

    cfg = _workspace()
    client = _client(cfg)
    assert client.post("/ask/stream", json={"question": "тест"}).status_code == 503
    assert HistoryStore(cfg.history.path).list_conversations("anonymous") == []


def test_stream_works_with_history_disabled():
    cfg = _workspace()
    build_index(cfg)
    cfg.history.enabled = False
    done = _events(_client(cfg).post("/ask/stream", json={"question": "сколько дней отпуска?"}))[-1]
    assert done["type"] == "done"
    assert done["conversation_id"] is None


# ------------------------------------------------------------- разметка

def test_ui_html_lives_in_its_own_module():
    from ragkb.ui import UI_HTML
    assert UI_HTML.lstrip().startswith("<!DOCTYPE html>")


def test_index_page_serves_ui():
    cfg = _workspace()
    build_index(cfg)
    body = _client(cfg).get("/").text
    assert "<title>" in body


if __name__ == "__main__":
    failed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"  ok   {name}")
            except Exception as exc:
                failed += 1
                print(f"  FAIL {name}: {type(exc).__name__}: {exc}")
    print(f"\n{'все тесты пройдены' if not failed else f'провалов: {failed}'}")
    raise SystemExit(1 if failed else 0)
