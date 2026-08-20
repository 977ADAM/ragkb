"""Тесты выбора модели. Запуск: python tests/test_models.py"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ragkb.config import Config, LLMConfig
from ragkb.models import available_models, resolve_model


def _cfg() -> LLMConfig:
    return LLMConfig(
        model="qwen2.5:7b-instruct",
        available=[
            {"name": "qwen2.5:7b-instruct", "title": "Быстрая"},
            {"name": "qwen2.5:14b-instruct", "title": "Точная"},
        ],
    )


def test_available_models_marks_default():
    items = available_models(_cfg())
    assert [i["name"] for i in items] == ["qwen2.5:7b-instruct", "qwen2.5:14b-instruct"]
    assert items[0]["default"] is True
    assert items[1]["default"] is False


def test_available_models_without_list_returns_current():
    items = available_models(LLMConfig(model="что-то:latest"))
    assert len(items) == 1
    assert items[0]["name"] == "что-то:latest"
    assert items[0]["default"] is True


def test_available_models_fills_missing_title():
    items = available_models(LLMConfig(model="a", available=[{"name": "a"}]))
    assert items[0]["title"] == "a"


def test_resolve_model_returns_default_when_not_requested():
    assert resolve_model(_cfg(), None) == "qwen2.5:7b-instruct"
    assert resolve_model(_cfg(), "") == "qwen2.5:7b-instruct"


def test_resolve_model_accepts_allowed():
    assert resolve_model(_cfg(), "qwen2.5:14b-instruct") == "qwen2.5:14b-instruct"


def test_resolve_model_rejects_unknown():
    try:
        resolve_model(_cfg(), "злая:модель")
    except ValueError as exc:
        assert "злая:модель" in str(exc)
        return
    raise AssertionError("ожидался отказ для модели вне списка")


def test_resolve_model_without_list_rejects_anything_but_current():
    cfg = LLMConfig(model="только-эта")
    assert resolve_model(cfg, "только-эта") == "только-эта"
    try:
        resolve_model(cfg, "другая")
    except ValueError:
        return
    raise AssertionError("при пустом списке допустима только текущая модель")


def test_config_reads_available_from_dict():
    cfg = Config.from_dict({"llm": {"model": "a", "available": [{"name": "a", "title": "А"}]}})
    assert cfg.llm.available == [{"name": "a", "title": "А"}]


# ------------------------------------------------- модель на запрос

import tempfile

from ragkb.pipeline import RAGPipeline, build_index

SAMPLE_DOC = (
    "# Политика\n\n## Отпуск\n\nЕжегодный отпуск составляет 28 календарных дней.\n"
)


def _pipeline() -> RAGPipeline:
    workdir = Path(tempfile.mkdtemp(prefix="ragkb-models-"))
    docs = workdir / "docs"
    docs.mkdir()
    (docs / "policy.md").write_text(SAMPLE_DOC, encoding="utf-8")
    cfg = Config(docs_dir=str(docs), index_dir=str(workdir / "index"))
    cfg.store.backend = "numpy"
    cfg.history.path = str(workdir / "history.sqlite3")
    build_index(cfg)
    return RAGPipeline(cfg)


def test_llm_for_returns_same_object_without_override():
    rag = _pipeline()
    assert rag._llm_for(None) is rag.llm
    assert rag._llm_for(rag.cfg.llm.model) is rag.llm


def test_llm_for_builds_new_llm_for_other_model():
    rag = _pipeline()
    # Экстрактивный бэкенд всегда зовётся «extractive» независимо от модели,
    # поэтому имя модели видно только на бэкенде, который его включает.
    # В сеть это не ходит: конструктор OllamaLLM лишь запоминает настройки.
    rag.cfg.llm.backend = "ollama"
    other = rag._llm_for("другая-модель")
    assert other is not rag.llm
    assert "другая-модель" in other.name


def test_llm_for_keeps_backend_and_settings():
    rag = _pipeline()
    rag.cfg.llm.temperature = 0.7
    other = rag._llm_for("другая-модель")
    assert other.cfg.temperature == 0.7
    assert other.cfg.backend == rag.cfg.llm.backend


def test_ask_records_used_model():
    # Прежняя версия сравнивала answer.llm_backend с rag.llm.name — но первое
    # присваивается из второго, а _llm_for(None) возвращает тот же rag.llm,
    # так что тест не мог провалиться ни при какой поломке переключения
    # модели. Проверяем именно переключение: просим другую модель и смотрим,
    # что в ответе записано её имя. В сеть не ходит: при недоступной Ollama
    # ask() ловит LLMError и собирает ответ экстрактивно, но llm_backend
    # успевает получить имя запрошенной модели до этого отказа.
    rag = _pipeline()
    rag.cfg.llm.backend = "ollama"
    other_model = "другая-модель"
    answer = rag.ask("сколько дней отпуска?", model=other_model)
    assert other_model in answer.llm_backend


def test_stream_answer_accepts_model():
    rag = _pipeline()
    hits, stream = rag.stream_answer("сколько дней отпуска?", model=None)
    assert isinstance(hits, list)
    assert "".join(stream)


# ------------------------------------------------- хранение модели

from ragkb.history import SCHEMA_VERSION, HistoryStore, connect, init_schema


def _store() -> HistoryStore:
    return HistoryStore(Path(tempfile.mkdtemp(prefix="ragkb-mstore-")) / "h.sqlite3")


def test_schema_version_is_three():
    assert SCHEMA_VERSION == 3


def test_message_carries_model():
    store = _store()
    cid = store.create_conversation("ivanov", "тема")
    store.append(cid, "ivanov", "assistant", "ответ", model="qwen2.5:7b-instruct")
    messages = store.get_messages(cid, "ivanov")
    assert messages[0].model == "qwen2.5:7b-instruct"
    assert messages[0].to_dict()["model"] == "qwen2.5:7b-instruct"


def test_model_defaults_to_empty():
    store = _store()
    cid = store.create_conversation("ivanov", "тема")
    store.append(cid, "ivanov", "user", "вопрос")
    assert store.get_messages(cid, "ivanov")[0].model == ""


def test_step_three_adds_column_to_v2_database():
    """База версии 2 должна получить столбец, не потеряв сообщений."""
    path = Path(tempfile.mkdtemp(prefix="ragkb-v2-")) / "h.sqlite3"
    with connect(path) as conn:
        # Создаём схему без последней ступени, как она выглядела в версии 2.
        conn.executescript(
            "CREATE TABLE conversations (id TEXT PRIMARY KEY, user TEXT NOT NULL,"
            " title TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL,"
            " updated_at TEXT NOT NULL);"
            "CREATE TABLE messages (id INTEGER PRIMARY KEY AUTOINCREMENT,"
            " conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,"
            " role TEXT NOT NULL CHECK (role IN ('user','assistant')),"
            " text TEXT NOT NULL, sources_json TEXT NOT NULL DEFAULT '[]',"
            " created_at TEXT NOT NULL);"
            "CREATE TABLE cleanup_state (id INTEGER PRIMARY KEY CHECK (id = 1),"
            " last_run TEXT NOT NULL);"
            "INSERT INTO cleanup_state (id, last_run) VALUES (1, '1970-01-01T00:00:00+00:00');"
        )
        conn.execute(
            "INSERT INTO conversations VALUES ('c1','ivanov','тема','2026-01-01','2026-01-01')"
        )
        conn.execute(
            "INSERT INTO messages (conversation_id, role, text, created_at)"
            " VALUES ('c1','user','старое сообщение','2026-01-01')"
        )
        conn.execute("PRAGMA user_version = 2")

    with connect(path) as conn:
        init_schema(conn)
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 3
        row = conn.execute("SELECT text, model FROM messages").fetchone()
        assert row["text"] == "старое сообщение"
        assert row["model"] == ""


# ------------------------------------------------- эндпоинты

import json


def _client(available=None):
    from fastapi.testclient import TestClient

    from ragkb.api import create_app

    workdir = Path(tempfile.mkdtemp(prefix="ragkb-api-"))
    docs = workdir / "docs"
    docs.mkdir()
    (docs / "policy.md").write_text(SAMPLE_DOC, encoding="utf-8")
    cfg = Config(docs_dir=str(docs), index_dir=str(workdir / "index"))
    cfg.store.backend = "numpy"
    cfg.auth.mode = "disabled"
    cfg.history.path = str(workdir / "history.sqlite3")
    if available is not None:
        cfg.llm.available = available
    build_index(cfg)
    return TestClient(create_app(cfg), raise_server_exceptions=False), cfg


ALLOWED = [{"name": "extractive-a", "title": "А"}, {"name": "extractive-b", "title": "Б"}]


def test_models_endpoint_lists_allowed():
    client, _cfg = _client(ALLOWED)
    body = client.get("/models").json()
    assert [m["name"] for m in body["models"]] == ["extractive-a", "extractive-b"]


def test_models_endpoint_requires_auth_when_enabled():
    from fastapi.testclient import TestClient

    from ragkb.api import create_app
    cfg = Config()
    cfg.auth.mode = "proxy"
    assert TestClient(create_app(cfg)).get("/models").status_code == 401


def test_ask_rejects_unknown_model():
    client, _ = _client(ALLOWED)
    resp = client.post("/ask", json={"question": "тест", "model": "злая:модель"})
    assert resp.status_code == 400, resp.status_code


def test_stream_rejects_unknown_model_before_streaming():
    client, _ = _client(ALLOWED)
    resp = client.post("/ask/stream", json={"question": "тест", "model": "злая:модель"})
    assert resp.status_code == 400, resp.status_code
    assert "ndjson" not in resp.headers.get("content-type", "")


def test_ask_accepts_allowed_model():
    client, cfg = _client(ALLOWED)
    cfg.llm.model = "extractive-a"
    body = client.post("/ask", json={"question": "сколько дней отпуска?",
                                     "model": "extractive-b"}).json()
    assert body["model"] == "extractive-b"


def test_stream_done_carries_model():
    client, _ = _client(ALLOWED)
    lines = client.post("/ask/stream", json={"question": "сколько дней отпуска?"}).text.splitlines()
    done = json.loads([line for line in lines if line.strip()][-1])
    assert done["type"] == "done"
    assert done["model"]


def test_top_k_out_of_range_gives_422():
    client, _ = _client()
    assert client.post("/ask", json={"question": "тест", "top_k": 0}).status_code == 422
    assert client.post("/ask", json={"question": "тест", "top_k": 99}).status_code == 422


def test_model_is_stored_with_message():
    from ragkb.history import HistoryStore

    client, cfg = _client(ALLOWED)
    body = client.post("/ask", json={"question": "сколько дней отпуска?",
                                     "model": "extractive-b"}).json()
    messages = HistoryStore(cfg.history.path).get_messages(body["conversation_id"], "anonymous")
    assert messages[1].model == "extractive-b"


def test_mini_yaml_handles_real_config_without_pyyaml():
    # Реальный config.yaml содержит llm.available — последовательность YAML,
    # которую _mini_yaml не умеет разбирать. Раньше её элементы («- name: ...»)
    # утекали в корень словаря отдельными ключами, и Config.from_dict падал
    # с TypeError на незнакомом аргументе. Проверяем, что фолбэк-парсер и
    # сборка конфигурации теперь уживаются на настоящем файле.
    from ragkb.config import _mini_yaml

    text = (Path(__file__).resolve().parents[1] / "config.yaml").read_text(encoding="utf-8")
    data = _mini_yaml(text)
    cfg = Config.from_dict(data)  # не должно бросать TypeError
    assert isinstance(cfg, Config)


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
