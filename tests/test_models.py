"""Тесты выбора модели. Запуск: python tests/test_models.py"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ragkb.config import Config, LLMConfig
from ragkb.models import available_models, resolve_model

INSTALLED = [
    {"id": "qwen2.5:7b-instruct", "context_window": 32768, "supports_tools": True},
    {"id": "qwen2.5:14b-instruct", "context_window": 32768, "supports_tools": True},
    {"id": "qwen3:4b", "context_window": 40960, "supports_tools": True},
]


def _cfg(available=None, model="qwen2.5:7b-instruct") -> LLMConfig:
    """Бэкенд ollama: только для него список берётся из установленного."""
    return LLMConfig(backend="ollama", model=model, available=available or [])


def test_available_models_lists_everything_installed():
    """Без фильтра предлагается всё, что установлено, — без хардкода."""
    items = available_models(_cfg(), installed=INSTALLED)
    assert [i["id"] for i in items] == [m["id"] for m in INSTALLED]


def test_available_models_filter_narrows_the_list():
    cfg = _cfg(available=[{"name": "qwen3:4b"}])
    assert [i["id"] for i in available_models(cfg, installed=INSTALLED)] == ["qwen3:4b"]


def test_available_models_marks_default():
    items = available_models(_cfg(model="qwen2.5:14b-instruct"), installed=INSTALLED)
    assert [i["is_default"] for i in items] == [False, True, False]


def test_default_falls_back_to_first_when_configured_model_absent():
    """Модель из настроек не установлена — подсвечиваем первую доступную."""
    items = available_models(_cfg(model="нет-такой"), installed=INSTALLED)
    assert items[0]["is_default"] is True


def test_available_models_carries_ollama_fields():
    item = available_models(_cfg(), installed=INSTALLED)[0]
    assert item["context_window"] == 32768
    assert item["supports_tools"] is True


def test_display_name_defaults_to_id():
    assert available_models(_cfg(), installed=INSTALLED)[0]["display_name"] == "qwen2.5:7b-instruct"


def test_display_name_taken_from_config_when_set():
    cfg = _cfg(available=[{"name": "qwen3:4b", "title": "Рассуждающая"}])
    assert available_models(cfg, installed=INSTALLED)[0]["display_name"] == "Рассуждающая"


def test_no_models_installed_gives_empty_list():
    """Пустой список означает режим поиска."""
    assert available_models(_cfg(), installed=[]) == []


def test_non_ollama_backend_reports_single_model():
    cfg = LLMConfig(backend="extractive", model="что-то")
    items = available_models(cfg)
    assert [i["id"] for i in items] == ["что-то"]
    assert items[0]["is_default"] is True


def test_installed_models_never_raises_when_ollama_is_down():
    """Список моделей не должен пропадать оттого, что недоступна Ollama."""
    from ragkb.models import installed_models
    assert installed_models("http://127.0.0.1:1") == []


def test_resolve_model_returns_default_when_not_requested():
    assert resolve_model(_cfg(), None, installed=INSTALLED) == "qwen2.5:7b-instruct"
    assert resolve_model(_cfg(), "", installed=INSTALLED) == "qwen2.5:7b-instruct"


def test_resolve_model_accepts_installed():
    assert resolve_model(_cfg(), "qwen3:4b", installed=INSTALLED) == "qwen3:4b"


def test_resolve_model_rejects_not_installed():
    try:
        resolve_model(_cfg(), "злая:модель", installed=INSTALLED)
    except ValueError as exc:
        assert "злая:модель" in str(exc)
        return
    raise AssertionError("ожидался отказ для неустановленной модели")


def test_resolve_model_without_models_returns_configured():
    """Моделей нет — возвращаем настройку, пайплайн уйдёт в режим поиска."""
    assert resolve_model(_cfg(), None, installed=[]) == "qwen2.5:7b-instruct"


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


# Экстрактивный бэкенд отдаёт ровно одну модель из настроек —
# это и делает тесты эндпоинтов независимыми от Ollama.
ALLOWED = None


def test_models_endpoint_lists_current_model():
    """На экстрактивном бэкенде перечислить установленное неоткуда —
    отдаётся одна модель из настроек, и она же выбрана по умолчанию."""
    client, cfg = _client()
    body = client.get("/models").json()
    assert [m["id"] for m in body["models"]] == [cfg.llm.model]
    assert body["models"][0]["is_default"] is True


def test_models_endpoint_requires_auth_when_enabled():
    from fastapi.testclient import TestClient

    from ragkb.api import create_app
    cfg = Config()
    cfg.auth.mode = "proxy"
    assert TestClient(create_app(cfg)).get("/models").status_code == 401


def test_ask_rejects_unknown_model():
    client, _ = _client()
    resp = client.post("/ask", json={"question": "тест", "model": "злая:модель"})
    assert resp.status_code == 400, resp.status_code


def test_stream_rejects_unknown_model_before_streaming():
    client, _ = _client()
    resp = client.post("/ask/stream", json={"question": "тест", "model": "злая:модель"})
    assert resp.status_code == 400, resp.status_code
    assert "ndjson" not in resp.headers.get("content-type", "")


def test_ask_accepts_allowed_model():
    client, cfg = _client()
    body = client.post(
        "/ask", json={"question": "сколько дней отпуска?", "model": cfg.llm.model}
    ).json()
    assert body["model"] == cfg.llm.model


def test_stream_done_carries_model():
    client, _ = _client()
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

    client, cfg = _client()
    body = client.post("/ask", json={"question": "сколько дней отпуска?",
                                     "model": cfg.llm.model}).json()
    messages = HistoryStore(cfg.history.path).get_messages(body["conversation_id"], "anonymous")
    assert messages[1].model == cfg.llm.model


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
