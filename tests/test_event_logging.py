"""Тесты приёма клиентской телеметрии. Запуск: python tests/test_event_logging.py"""
from __future__ import annotations

import io
import json
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

SESSION = "3f2b1c40-9a7e-4d51-9c3a-2e5f7b8d1a20"
URL = "/event_logging/v1/batch"


def _client(auth: str = "disabled"):
    from fastapi.testclient import TestClient

    from ragkb.api import create_app
    from ragkb.config import Config

    tmp = Path(tempfile.mkdtemp(prefix="ragkb-events-"))
    cfg = Config()
    cfg.index_dir = str(tmp / "нет-индекса")
    cfg.auth.mode = auth
    cfg.history.enabled = False
    return TestClient(create_app(cfg), raise_server_exceptions=False)


def _post(client, payload):
    """Отправляет батч и возвращает (ответ, записанные в журнал строки)."""
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        resp = client.post(URL, json=payload)
    lines = [
        json.loads(line)
        for line in buffer.getvalue().splitlines()
        if line.startswith("{")
    ]
    return resp, lines


def test_accepts_batch_and_reports_count():
    client = _client()
    resp, _ = _post(
        client,
        {"session_id": SESSION, "events": [{"name": "app_start"}, {"name": "ask"}]},
    )
    assert resp.status_code == 200, resp.status_code
    assert resp.json() == {"accepted": 2}


def test_writes_one_line_per_event():
    # Журнал забирает docker/journald построчно: склеенная запись там
    # разбирается уже вручную.
    _, lines = _post(
        _client(), {"session_id": SESSION, "events": [{"name": "a"}, {"name": "b"}]}
    )
    assert [line["event"] for line in lines] == ["a", "b"]


def test_record_carries_user_and_session():
    _, lines = _post(_client(), {"session_id": SESSION, "events": [{"name": "app_start"}]})
    assert lines[0]["user"] == "anonymous"
    assert lines[0]["session_id"] == SESSION


def test_record_carries_server_time():
    # Время клиента может врать: часы на рабочей станции переводят, вкладка
    # висит сутками. Своё время сервера в записи обязательно.
    _, lines = _post(_client(), {"session_id": SESSION, "events": [{"name": "app_start"}]})
    assert lines[0]["received_at"].endswith("+00:00")


def test_client_timestamp_is_kept_when_given():
    _, lines = _post(
        _client(),
        {
            "session_id": SESSION,
            "events": [{"name": "app_start", "ts": "2026-08-21T10:00:00+00:00"}],
        },
    )
    assert lines[0]["ts"] == "2026-08-21T10:00:00+00:00"


def test_properties_are_kept():
    _, lines = _post(
        _client(),
        {"session_id": SESSION, "events": [{"name": "ask", "props": {"model": "qwen"}}]},
    )
    assert lines[0]["props"] == {"model": "qwen"}


def test_empty_batch_is_refused():
    resp, _ = _post(_client(), {"session_id": SESSION, "events": []})
    assert resp.status_code == 422, resp.status_code


def test_oversized_batch_is_refused():
    # Верхняя граница нужна, чтобы одна вкладка не могла залить журнал
    # мегабайтом за запрос.
    events = [{"name": "a"} for _ in range(101)]
    resp, _ = _post(_client(), {"session_id": SESSION, "events": events})
    assert resp.status_code == 422, resp.status_code


def test_long_event_name_is_refused():
    resp, _ = _post(_client(), {"session_id": SESSION, "events": [{"name": "я" * 65}]})
    assert resp.status_code == 422, resp.status_code


def test_oversized_properties_are_refused():
    big = {"payload": "я" * 3000}
    resp, _ = _post(_client(), {"session_id": SESSION, "events": [{"name": "a", "props": big}]})
    assert resp.status_code == 422, resp.status_code


def test_non_uuid_session_is_refused():
    resp, _ = _post(_client(), {"session_id": "не-uuid", "events": [{"name": "a"}]})
    assert resp.status_code == 422, resp.status_code


def test_requires_authentication():
    resp, lines = _post(
        _client(auth="proxy"), {"session_id": SESSION, "events": [{"name": "a"}]}
    )
    assert resp.status_code == 401, resp.status_code
    # Неаутентифицированный запрос не должен оставлять следов в журнале.
    assert lines == []


def test_unknown_event_fields_are_ignored():
    # Клиент может быть новее сервера. Незнакомое поле не повод терять батч.
    resp, lines = _post(
        _client(),
        {"session_id": SESSION, "events": [{"name": "a", "какое-то_поле": 1}]},
    )
    assert resp.status_code == 200, resp.status_code
    assert lines[0]["event"] == "a"


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
