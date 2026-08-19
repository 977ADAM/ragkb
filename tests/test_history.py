"""Тесты хранилища диалогов. Запуск: python tests/test_history.py"""
from __future__ import annotations

import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ragkb.history import SCHEMA_VERSION, connect, init_schema, utcnow


def _fresh_db() -> Path:
    """Пустая база во временном каталоге. Не :memory: — там WAL недоступен."""
    return Path(tempfile.mkdtemp(prefix="ragkb-history-")) / "history.sqlite3"


# --------------------------------------------------------------- соединение

def test_foreign_keys_are_enabled():
    with connect(_fresh_db()) as conn:
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1


def test_journal_mode_is_wal():
    with connect(_fresh_db()) as conn:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"


def test_busy_timeout_is_set():
    with connect(_fresh_db()) as conn:
        assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == 5000


def test_rows_are_accessible_by_name():
    path = _fresh_db()
    with connect(path) as conn:
        init_schema(conn)
        conn.execute(
            "INSERT INTO conversations (id, user, title, created_at, updated_at)"
            " VALUES ('c1', 'ivanov', 'тема', '2026-01-01T00:00:00+00:00',"
            " '2026-01-01T00:00:00+00:00')"
        )
    with connect(path) as conn:
        row = conn.execute("SELECT title FROM conversations").fetchone()
        assert row["title"] == "тема"


# -------------------------------------------------------------------- схема

def test_init_schema_sets_user_version():
    path = _fresh_db()
    with connect(path) as conn:
        init_schema(conn)
        assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION


def test_init_schema_is_idempotent():
    path = _fresh_db()
    with connect(path) as conn:
        init_schema(conn)
        init_schema(conn)
        names = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        assert {"conversations", "messages", "cleanup_state"} <= names


def test_cascade_removes_messages():
    path = _fresh_db()
    with connect(path) as conn:
        init_schema(conn)
        conn.execute(
            "INSERT INTO conversations (id, user, title, created_at, updated_at)"
            " VALUES ('c1', 'ivanov', 'тема', '2026-01-01T00:00:00+00:00',"
            " '2026-01-01T00:00:00+00:00')"
        )
        conn.execute(
            "INSERT INTO messages (conversation_id, role, text, created_at)"
            " VALUES ('c1', 'user', 'вопрос', '2026-01-01T00:00:00+00:00')"
        )
        conn.execute("DELETE FROM conversations WHERE id = 'c1'")
        assert conn.execute("SELECT count(*) FROM messages").fetchone()[0] == 0


def test_role_is_constrained():
    path = _fresh_db()
    with connect(path) as conn:
        init_schema(conn)
        conn.execute(
            "INSERT INTO conversations (id, user, title, created_at, updated_at)"
            " VALUES ('c1', 'ivanov', 'тема', '2026-01-01T00:00:00+00:00',"
            " '2026-01-01T00:00:00+00:00')"
        )
        try:
            conn.execute(
                "INSERT INTO messages (conversation_id, role, text, created_at)"
                " VALUES ('c1', 'система', 'нельзя', '2026-01-01T00:00:00+00:00')"
            )
        except sqlite3.IntegrityError:
            return
        raise AssertionError("ожидалось нарушение CHECK по роли")


def test_newer_schema_version_is_refused():
    path = _fresh_db()
    with connect(path) as conn:
        init_schema(conn)
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION + 1}")
    with connect(path) as conn:
        try:
            init_schema(conn)
        except RuntimeError as exc:
            assert str(SCHEMA_VERSION + 1) in str(exc), str(exc)
            return
        raise AssertionError("ожидался отказ работать со схемой из будущего")


def test_utcnow_is_timezone_aware():
    assert utcnow().tzinfo is not None


# ------------------------------------------------------------- хранилище

from ragkb.config import HistoryConfig
from ragkb.history import HistoryStore, make_title


def _store() -> HistoryStore:
    return HistoryStore(_fresh_db())


def test_history_config_defaults():
    cfg = HistoryConfig()
    assert cfg.enabled is True
    assert cfg.retention_days == 90
    assert cfg.window == 3


def test_config_exposes_history_section():
    from ragkb.config import Config
    cfg = Config.from_dict({"history": {"retention_days": 7, "window": 5}})
    assert cfg.history.retention_days == 7
    assert cfg.history.window == 5


def test_condense_uses_configured_window_not_hardcoded_three():
    """history.window должен реально доходить до _condense.

    Строим RAGPipeline в обход __init__ (он поднимает индекс, эмбеддер и
    LLM — тут нужен только self.cfg и self.llm): _condense использует
    только их. При хардкоде history[-3:] этот тест провалился бы, потому
    что в промпт попали бы все три пары, включая самую старую.
    """
    from ragkb.config import Config
    from ragkb.pipeline import RAGPipeline

    cfg = Config()
    cfg.history.window = 1

    captured: dict[str, str] = {}

    class FakeLLM:
        def generate(self, system: str, prompt: str) -> str:
            captured["prompt"] = prompt
            return "переформулировано"

    pipeline = object.__new__(RAGPipeline)
    pipeline.cfg = cfg
    pipeline.llm = FakeLLM()

    history = [("вопрос1", "ответ1"), ("вопрос2", "ответ2"), ("вопрос3", "ответ3")]
    pipeline._condense("новый вопрос", history)

    assert "вопрос1" not in captured["prompt"]
    assert "вопрос2" not in captured["prompt"]
    assert "вопрос3" in captured["prompt"]


def test_make_title_truncates_long_question():
    title = make_title("а" * 200)
    assert len(title) <= 60


def test_make_title_keeps_short_question():
    assert make_title("Сколько дней отпуска?") == "Сколько дней отпуска?"


def test_make_title_collapses_whitespace():
    assert make_title("  Сколько   дней\nотпуска? ") == "Сколько дней отпуска?"


def test_create_and_list_conversation():
    store = _store()
    cid = store.create_conversation("ivanov", "Отпуск")
    items = store.list_conversations("ivanov")
    assert len(items) == 1
    assert items[0].id == cid
    assert items[0].title == "Отпуск"


def test_conversations_of_other_user_are_invisible():
    store = _store()
    store.create_conversation("ivanov", "Отпуск")
    assert store.list_conversations("petrov") == []


def test_owns_is_false_for_other_user():
    store = _store()
    cid = store.create_conversation("ivanov", "Отпуск")
    assert store.owns(cid, "ivanov")
    assert not store.owns(cid, "petrov")


def test_append_and_read_messages():
    store = _store()
    cid = store.create_conversation("ivanov", "Отпуск")
    store.append(cid, "ivanov", "user", "Сколько дней?")
    store.append(cid, "ivanov", "assistant", "28 календарных дней [1].",
                 [{"n": 1, "citation": "Регламент", "source": "data/docs/o.md"}])
    messages = store.get_messages(cid, "ivanov")
    assert [m.role for m in messages] == ["user", "assistant"]
    assert messages[1].sources[0]["source"] == "data/docs/o.md"


def test_append_to_other_conversation_is_refused():
    store = _store()
    cid = store.create_conversation("ivanov", "Отпуск")
    assert store.append(cid, "petrov", "user", "чужое") is False
    assert store.get_messages(cid, "ivanov") == []


def test_get_messages_of_other_user_returns_none():
    store = _store()
    cid = store.create_conversation("ivanov", "Отпуск")
    store.append(cid, "ivanov", "user", "Сколько дней?")
    assert store.get_messages(cid, "petrov") is None


def test_get_messages_of_unknown_conversation_returns_none():
    assert _store().get_messages("нет-такого", "ivanov") is None


def test_recent_turns_pairs_question_and_answer():
    store = _store()
    cid = store.create_conversation("ivanov", "Отпуск")
    store.append(cid, "ivanov", "user", "в1")
    store.append(cid, "ivanov", "assistant", "о1")
    store.append(cid, "ivanov", "user", "в2")
    store.append(cid, "ivanov", "assistant", "о2")
    assert store.recent_turns(cid, "ivanov", window=3) == [("в1", "о1"), ("в2", "о2")]


def test_recent_turns_respects_window():
    store = _store()
    cid = store.create_conversation("ivanov", "Отпуск")
    for i in range(5):
        store.append(cid, "ivanov", "user", f"в{i}")
        store.append(cid, "ivanov", "assistant", f"о{i}")
    turns = store.recent_turns(cid, "ivanov", window=2)
    assert turns == [("в3", "о3"), ("в4", "о4")]


def test_recent_turns_drops_unanswered_question():
    store = _store()
    cid = store.create_conversation("ivanov", "Отпуск")
    store.append(cid, "ivanov", "user", "в1")
    store.append(cid, "ivanov", "assistant", "о1")
    store.append(cid, "ivanov", "user", "без ответа")
    assert store.recent_turns(cid, "ivanov", window=3) == [("в1", "о1")]


def test_recent_turns_for_other_user_is_empty():
    store = _store()
    cid = store.create_conversation("ivanov", "Отпуск")
    store.append(cid, "ivanov", "user", "в1")
    store.append(cid, "ivanov", "assistant", "о1")
    assert store.recent_turns(cid, "petrov", window=3) == []


def test_delete_removes_conversation_and_messages():
    store = _store()
    cid = store.create_conversation("ivanov", "Отпуск")
    store.append(cid, "ivanov", "user", "в1")
    assert store.delete_conversation(cid, "ivanov") is True
    assert store.list_conversations("ivanov") == []
    assert store.get_messages(cid, "ivanov") is None


def test_delete_of_other_user_is_refused():
    store = _store()
    cid = store.create_conversation("ivanov", "Отпуск")
    assert store.delete_conversation(cid, "petrov") is False
    assert len(store.list_conversations("ivanov")) == 1


def test_appending_touches_updated_at():
    store = _store()
    cid = store.create_conversation("ivanov", "Отпуск")
    before = store.list_conversations("ivanov")[0].updated_at
    store.append(cid, "ivanov", "user", "в1")
    after = store.list_conversations("ivanov")[0].updated_at
    assert after >= before


def test_list_puts_recent_first():
    store = _store()
    old = store.create_conversation("ivanov", "Старый")
    new = store.create_conversation("ivanov", "Новый")
    with connect(store.path) as conn:
        conn.execute("UPDATE conversations SET updated_at = ? WHERE id = ?",
                     ("2020-01-01T00:00:00+00:00", old))
    assert [c.id for c in store.list_conversations("ivanov")] == [new, old]


# --------------------------------------------------------------- уборка

import threading
from datetime import timedelta


def test_cleanup_removes_expired():
    store = HistoryStore(_fresh_db(), retention_days=30)
    old = store.create_conversation("ivanov", "Старый")
    with connect(store.path) as conn:
        conn.execute("UPDATE conversations SET updated_at = ? WHERE id = ?",
                     ((utcnow() - timedelta(days=60)).isoformat(), old))
    assert store.cleanup() == 1
    assert store.list_conversations("ivanov") == []


def test_cleanup_keeps_fresh():
    store = HistoryStore(_fresh_db(), retention_days=30)
    store.create_conversation("ivanov", "Свежий")
    assert store.cleanup() == 0
    assert len(store.list_conversations("ivanov")) == 1


def test_cleanup_removes_messages_of_expired():
    store = HistoryStore(_fresh_db(), retention_days=30)
    old = store.create_conversation("ivanov", "Старый")
    store.append(old, "ivanov", "user", "в1")
    with connect(store.path) as conn:
        conn.execute("UPDATE conversations SET updated_at = ? WHERE id = ?",
                     ((utcnow() - timedelta(days=60)).isoformat(), old))
    store.cleanup()
    with connect(store.path) as conn:
        assert conn.execute("SELECT count(*) FROM messages").fetchone()[0] == 0


def test_cleanup_does_not_repeat_within_a_day():
    store = HistoryStore(_fresh_db(), retention_days=30)
    for _ in range(2):
        cid = store.create_conversation("ivanov", "Старый")
        with connect(store.path) as conn:
            conn.execute("UPDATE conversations SET updated_at = ? WHERE id = ?",
                         ((utcnow() - timedelta(days=60)).isoformat(), cid))
    assert store.cleanup() == 2
    # Второй вызов подряд не должен ничего делать: сутки не прошли.
    cid = store.create_conversation("ivanov", "Ещё старый")
    with connect(store.path) as conn:
        conn.execute("UPDATE conversations SET updated_at = ? WHERE id = ?",
                     ((utcnow() - timedelta(days=60)).isoformat(), cid))
    assert store.cleanup() == 0
    assert len(store.list_conversations("ivanov")) == 1


def test_cleanup_runs_again_after_a_day():
    store = HistoryStore(_fresh_db(), retention_days=30)
    assert store.cleanup() == 0
    cid = store.create_conversation("ivanov", "Старый")
    with connect(store.path) as conn:
        conn.execute("UPDATE conversations SET updated_at = ? WHERE id = ?",
                     ((utcnow() - timedelta(days=60)).isoformat(), cid))
    # Сутки спустя отметка снова просрочена.
    assert store.cleanup(now=utcnow() + timedelta(days=2)) == 1


def test_cleanup_is_limited_by_batch():
    store = HistoryStore(_fresh_db(), retention_days=30)
    stale = (utcnow() - timedelta(days=60)).isoformat()
    for _ in range(5):
        cid = store.create_conversation("ivanov", "Старый")
        with connect(store.path) as conn:
            conn.execute("UPDATE conversations SET updated_at = ? WHERE id = ?",
                         (stale, cid))
    assert store.cleanup(batch=2) == 2
    assert len(store.list_conversations("ivanov")) == 3


def test_concurrent_cleanup_claims_marker_once():
    """Различает атомарный гейт от наивного «прочитал — сравнил — записал».

    ВАЖНО про эту версию теста: раньше тут сравнивались итоговые суммы
    удалённого и то, сколько диалогов осталось после двух конкурентных
    cleanup(). После задачи 4 (доубор остатка: если удалена ровно целая
    партия, отметка сама переоткрывает гейт) это сравнение перестало
    что-либо различать — я проверил это explicitly, подставив заведомо
    наивную (нерасширенную WHERE) реализацию гейта: при любом batch
    результат («сколько осталось», «сумма удалённого по потокам») у
    наивной и атомарной реализаций совпадает один в один, потому что
    DELETE идемпотентен по предикату, а finding 4 намеренно допускает
    второй проход, когда первый выбрал партию целиком, — то же самое
    внешне делает и баг с гонкой. Иными словами, сравнением итогов
    отличить гейт с багом от гейта без бага в этой версии кода уже
    нельзя ни при каком batch.

    Поэтому здесь проверяется не итог, а факт: сколько раз реально
    выполнился DELETE FROM conversations — через подмену sqlite3.connect
    на фабрику соединений, считающую такие вызовы. batch заведомо больше
    числа просроченных (не зацепляет доборку остатка задачи 4: у неё
    removed == batch не наступает, потому что удалить получается меньше
    целой партии):
      - атомарный гейт: claim (UPDATE ... WHERE last_run < ?) успевает
        ровно у одного потока — только он и выполняет DELETE, второй
        получает отказ гейта и возвращается, не долетев до DELETE;
      - наивный гейт (SELECT, потом безусловная запись): оба потока
        успевают прочитать просроченную отметку до того, как её обновит
        другой, и оба выполняют DELETE — раз ни на что не влияет
        (данные уже мог забрать первый), но статистика вызовов ловит
        именно это: DELETE выполнился бы дважды, а не один раз.
    """
    store = HistoryStore(_fresh_db(), retention_days=30)
    stale = (utcnow() - timedelta(days=60)).isoformat()
    for _ in range(4):
        cid = store.create_conversation("ivanov", "Старый")
        with connect(store.path) as conn:
            conn.execute("UPDATE conversations SET updated_at = ? WHERE id = ?",
                         (stale, cid))

    delete_calls: list[int] = []
    lock = threading.Lock()

    class _CountingConnection(sqlite3.Connection):
        def execute(self, sql, *args, **kwargs):
            if isinstance(sql, str) and sql.strip().startswith("DELETE FROM conversations"):
                with lock:
                    delete_calls.append(1)
            return super().execute(sql, *args, **kwargs)

    original_connect = sqlite3.connect

    def counting_connect(*args, **kwargs):
        kwargs.setdefault("factory", _CountingConnection)
        return original_connect(*args, **kwargs)

    def run():
        store.cleanup(batch=10)

    sqlite3.connect = counting_connect
    try:
        threads = [threading.Thread(target=run) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
    finally:
        sqlite3.connect = original_connect

    # DELETE выполнился ровно у победителя гонки за гейт — не у обоих потоков.
    assert len(delete_calls) == 1, delete_calls
    assert len(store.list_conversations("ivanov")) == 0


def test_cleanup_drains_remainder_without_waiting_a_day():
    """Если удалена ровно целая партия, отметка сразу возвращается в прошлое.

    При пяти просроченных и batch=2 два вызова подряд должны удалить
    по 2 (а не 2 и 0, как было бы при суточном гейте, не различающем
    «партия кончилась» от «просроченного не осталось»). Третий вызов
    добирает оставшийся один диалог.
    """
    store = HistoryStore(_fresh_db(), retention_days=30)
    stale = (utcnow() - timedelta(days=60)).isoformat()
    for _ in range(5):
        cid = store.create_conversation("ivanov", "Старый")
        with connect(store.path) as conn:
            conn.execute("UPDATE conversations SET updated_at = ? WHERE id = ?",
                         (stale, cid))
    assert store.cleanup(batch=2) == 2
    assert store.cleanup(batch=2) == 2
    assert store.cleanup(batch=2) == 1
    assert store.list_conversations("ivanov") == []


# --------------------------------------------------------- /ask и диалоги

def _app_client(tmp: Path, enabled: bool = True):
    """Приложение с историей, но без индекса.

    Пайплайн не поднимется, поэтому проверяем только то, что происходит
    до обращения к нему: разбор запроса, владение диалогом, ведение истории
    проверяются отдельно на HistoryStore.
    """
    from fastapi.testclient import TestClient

    from ragkb.api import create_app
    from ragkb.config import Config

    cfg = Config()
    cfg.index_dir = str(tmp / "нет-индекса")
    cfg.auth.mode = "disabled"
    cfg.history.enabled = enabled
    cfg.history.path = str(tmp / "history.sqlite3")
    return TestClient(create_app(cfg), raise_server_exceptions=False)


def test_ask_with_foreign_conversation_gives_404():
    tmp = Path(tempfile.mkdtemp(prefix="ragkb-api-"))
    client = _app_client(tmp)
    store = HistoryStore(tmp / "history.sqlite3")
    foreign = store.create_conversation("petrov", "Чужой")
    resp = client.post("/ask", json={"question": "тест", "conversation_id": foreign})
    assert resp.status_code == 404, resp.status_code


def test_ask_with_unknown_conversation_gives_404():
    tmp = Path(tempfile.mkdtemp(prefix="ragkb-api-"))
    resp = _app_client(tmp).post(
        "/ask", json={"question": "тест", "conversation_id": "нет-такого"})
    assert resp.status_code == 404, resp.status_code


def test_ask_request_accepts_conversation_id_field():
    from ragkb.api import AskRequest
    req = AskRequest(question="тест", conversation_id="c1")
    assert req.conversation_id == "c1"


def test_ask_request_conversation_id_defaults_to_none():
    from ragkb.api import AskRequest
    assert AskRequest(question="тест").conversation_id is None


def test_history_disabled_ignores_conversation_id():
    tmp = Path(tempfile.mkdtemp(prefix="ragkb-api-"))
    client = _app_client(tmp, enabled=False)
    # При выключенной истории проверять владение нечем — до 404 дело
    # не доходит, запрос уходит в пайплайн и падает на отсутствии индекса.
    resp = client.post("/ask", json={"question": "тест", "conversation_id": "любой"})
    assert resp.status_code == 503, resp.status_code


def test_failed_pipeline_leaves_no_empty_conversation():
    tmp = Path(tempfile.mkdtemp(prefix="ragkb-api-"))
    client = _app_client(tmp)
    # Индекса нет, поэтому пайплайн ответит 503.
    assert client.post("/ask", json={"question": "тест"}).status_code == 503
    store = HistoryStore(tmp / "history.sqlite3")
    assert store.list_conversations("anonymous") == []


def _working_ask_client(tmp: Path):
    """Клиент с настоящим (маленьким) индексом — /ask должен ответить 200.

    В отличие от _app_client, тут пайплайн реально отвечает: нужен, чтобы
    проверить поведение после получения ответа — что запись в историю
    не роняет уже посчитанный ответ.
    """
    from fastapi.testclient import TestClient

    from ragkb.api import create_app
    from ragkb.config import Config
    from ragkb.pipeline import build_index

    docs = tmp / "docs"
    docs.mkdir()
    (docs / "policy.md").write_text(
        "# Политика\n\n## Отпуск\n\nЕжегодный отпуск составляет 28"
        " календарных дней [1].\n",
        encoding="utf-8",
    )
    cfg = Config(docs_dir=str(docs), index_dir=str(tmp / "index"))
    cfg.store.backend = "numpy"
    cfg.auth.mode = "disabled"
    cfg.history.enabled = True
    cfg.history.path = str(tmp / "history.sqlite3")
    build_index(cfg)
    return TestClient(create_app(cfg), raise_server_exceptions=False)


def test_ask_response_warns_when_append_returns_false():
    """append() вернул False (диалог исчез между owns() и записью) —
    ответ пользователя не должен теряться, но предупреждение обязано быть."""
    tmp = Path(tempfile.mkdtemp(prefix="ragkb-ask-warn-"))
    client = _working_ask_client(tmp)
    original = HistoryStore.append
    HistoryStore.append = lambda self, *a, **k: False
    try:
        resp = client.post("/ask", json={"question": "сколько дней отпуска?"})
    finally:
        HistoryStore.append = original
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["conversation_id"]
    assert any("не сохранён" in w for w in body["warnings"])


def test_ask_response_warns_when_append_raises():
    """append() бросил исключение (истёк таймаут блокировки SQLite) —
    дорого посчитанный ответ всё равно должен дойти до клиента."""
    tmp = Path(tempfile.mkdtemp(prefix="ragkb-ask-warn-"))
    client = _working_ask_client(tmp)

    def _boom(self, *a, **k):
        raise sqlite3.OperationalError("database is locked")

    original = HistoryStore.append
    HistoryStore.append = _boom
    try:
        resp = client.post("/ask", json={"question": "сколько дней отпуска?"})
    finally:
        HistoryStore.append = original
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "28" in body["answer"]
    assert any("не сохранён" in w for w in body["warnings"])


# ------------------------------------------------- эндпоинты /conversations

def test_conversations_list_is_empty_at_start():
    tmp = Path(tempfile.mkdtemp(prefix="ragkb-api-"))
    resp = _app_client(tmp).get("/conversations")
    assert resp.status_code == 200
    assert resp.json() == {"conversations": [], "total": 0}


def test_conversations_list_shows_own_only():
    tmp = Path(tempfile.mkdtemp(prefix="ragkb-api-"))
    client = _app_client(tmp)
    store = HistoryStore(tmp / "history.sqlite3")
    store.create_conversation("anonymous", "Мой")
    store.create_conversation("petrov", "Чужой")
    titles = [c["title"] for c in client.get("/conversations").json()["conversations"]]
    assert titles == ["Мой"]


def test_conversations_list_reports_total_beyond_default_limit():
    """У пользователя с 60 диалогами 51-й и далее должны быть достижимы."""
    store = HistoryStore(_fresh_db())
    for i in range(60):
        store.create_conversation("ivanov", f"Диалог {i}")
    assert store.count_conversations("ivanov") == 60
    assert len(store.list_conversations("ivanov")) == 50  # значение по умолчанию
    rest = store.list_conversations("ivanov", limit=50, offset=50)
    assert len(rest) == 10


def test_conversations_endpoint_exposes_limit_offset_and_total():
    tmp = Path(tempfile.mkdtemp(prefix="ragkb-api-"))
    client = _app_client(tmp)
    store = HistoryStore(tmp / "history.sqlite3")
    for i in range(60):
        store.create_conversation("anonymous", f"Диалог {i}")
    body = client.get("/conversations").json()
    assert body["total"] == 60
    assert len(body["conversations"]) == 50

    page2 = client.get("/conversations", params={"limit": 50, "offset": 50}).json()
    assert page2["total"] == 60
    assert len(page2["conversations"]) == 10


def test_conversations_endpoint_rejects_limit_out_of_range():
    tmp = Path(tempfile.mkdtemp(prefix="ragkb-api-"))
    client = _app_client(tmp)
    assert client.get("/conversations", params={"limit": 501}).status_code == 422
    assert client.get("/conversations", params={"limit": 0}).status_code == 422
    assert client.get("/conversations", params={"offset": -1}).status_code == 422


def test_conversation_messages_are_returned():
    tmp = Path(tempfile.mkdtemp(prefix="ragkb-api-"))
    client = _app_client(tmp)
    store = HistoryStore(tmp / "history.sqlite3")
    cid = store.create_conversation("anonymous", "Отпуск")
    store.append(cid, "anonymous", "user", "Сколько дней?")
    store.append(cid, "anonymous", "assistant", "28 дней [1].",
                 [{"n": 1, "citation": "Регламент", "source": "data/docs/нет.md"}])
    body = client.get(f"/conversations/{cid}").json()
    assert body["id"] == cid
    assert [m["role"] for m in body["messages"]] == ["user", "assistant"]


def test_foreign_conversation_gives_404():
    tmp = Path(tempfile.mkdtemp(prefix="ragkb-api-"))
    client = _app_client(tmp)
    store = HistoryStore(tmp / "history.sqlite3")
    foreign = store.create_conversation("petrov", "Чужой")
    assert client.get(f"/conversations/{foreign}").status_code == 404


def test_unknown_conversation_gives_404():
    tmp = Path(tempfile.mkdtemp(prefix="ragkb-api-"))
    assert _app_client(tmp).get("/conversations/нет-такого").status_code == 404


def test_delete_own_conversation():
    tmp = Path(tempfile.mkdtemp(prefix="ragkb-api-"))
    client = _app_client(tmp)
    store = HistoryStore(tmp / "history.sqlite3")
    cid = store.create_conversation("anonymous", "Отпуск")
    assert client.delete(f"/conversations/{cid}").status_code == 200
    assert client.get("/conversations").json() == {"conversations": [], "total": 0}


def test_delete_foreign_conversation_gives_404():
    tmp = Path(tempfile.mkdtemp(prefix="ragkb-api-"))
    client = _app_client(tmp)
    store = HistoryStore(tmp / "history.sqlite3")
    foreign = store.create_conversation("petrov", "Чужой")
    assert client.delete(f"/conversations/{foreign}").status_code == 404
    assert len(store.list_conversations("petrov")) == 1


def test_conversations_disabled_history_gives_404():
    tmp = Path(tempfile.mkdtemp(prefix="ragkb-api-"))
    assert _app_client(tmp, enabled=False).get("/conversations").status_code == 404


def test_missing_source_is_not_marked_available_without_index():
    tmp = Path(tempfile.mkdtemp(prefix="ragkb-api-"))
    client = _app_client(tmp)
    store = HistoryStore(tmp / "history.sqlite3")
    cid = store.create_conversation("anonymous", "Отпуск")
    store.append(cid, "anonymous", "assistant", "ответ [1].",
                 [{"n": 1, "citation": "Регламент", "source": "data/docs/нет.md"}])
    sources = client.get(f"/conversations/{cid}").json()["messages"][0]["sources"]
    # Индекса нет — состав неизвестен, поэтому пометку не ставим совсем.
    assert "available" not in sources[0]


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
