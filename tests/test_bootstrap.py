"""Тесты стартовой ручки. Запуск: python tests/test_bootstrap.py"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ragkb.history import HistoryStore

SESSION = "3f2b1c40-9a7e-4d51-9c3a-2e5f7b8d1a20"


def _client(tmp: Path, *, history: bool = True, org: dict | None = None,
            auth: str = "disabled"):
    """Приложение без индекса: старт обязан работать и на пустой базе."""
    from fastapi.testclient import TestClient

    from ragkb.api import create_app
    from ragkb.config import Config, OrganizationConfig

    cfg = Config()
    cfg.index_dir = str(tmp / "нет-индекса")
    cfg.auth.mode = auth
    cfg.history.enabled = history
    cfg.history.path = str(tmp / "history.sqlite3")
    if org is not None:
        cfg.organization = OrganizationConfig(**org)
    return TestClient(create_app(cfg), raise_server_exceptions=False)


def _tmp() -> Path:
    return Path(tempfile.mkdtemp(prefix="ragkb-bootstrap-"))


def test_returns_session_id_back():
    # Идентификатор сессии придумывает клиент. Сервер возвращает его эхом,
    # чтобы клиент убедился: ответ пришёл на его запрос, а не из кеша.
    body = _client(_tmp()).get(f"/bootstrap/{SESSION}/app_start").json()
    assert body["session_id"] == SESSION


def test_rejects_non_uuid_session():
    resp = _client(_tmp()).get("/bootstrap/не-uuid/app_start")
    assert resp.status_code == 422, resp.status_code


def test_carries_current_user():
    body = _client(_tmp()).get(f"/bootstrap/{SESSION}/app_start").json()
    assert body["user"]["name"] == "anonymous"


def test_marks_admin_by_group():
    tmp = _tmp()
    client = _client(tmp, auth="proxy")
    resp = client.get(
        f"/bootstrap/{SESSION}/app_start",
        headers={
            "X-Forwarded-Preferred-Username": "ivanov",
            "X-Forwarded-Groups": "ragkb-admins,everyone",
        },
    )
    assert resp.json()["user"]["is_admin"] is True


def test_ordinary_user_is_not_admin():
    tmp = _tmp()
    resp = _client(tmp, auth="proxy").get(
        f"/bootstrap/{SESSION}/app_start",
        headers={"X-Forwarded-Preferred-Username": "ivanov"},
    )
    assert resp.json()["user"]["is_admin"] is False


def test_requires_authentication():
    resp = _client(_tmp(), auth="proxy").get(f"/bootstrap/{SESSION}/app_start")
    assert resp.status_code == 401, resp.status_code


def test_carries_configured_organization():
    body = _client(_tmp(), org={"name": "Акме"}).get(
        f"/bootstrap/{SESSION}/app_start").json()
    assert body["organization"] == {"id": "Акме", "name": "Акме", "description": ""}


def test_organization_is_null_when_not_configured():
    # Не пустой объект: «не настроено» и «настроено пустым» — разные вещи.
    body = _client(_tmp()).get(f"/bootstrap/{SESSION}/app_start").json()
    assert body["organization"] is None


def test_carries_own_conversations_only():
    tmp = _tmp()
    client = _client(tmp)
    store = HistoryStore(tmp / "history.sqlite3")
    mine = store.create_conversation("anonymous", "Мой")
    store.create_conversation("petrov", "Чужой")
    body = client.get(f"/bootstrap/{SESSION}/app_start").json()
    assert [c["id"] for c in body["conversations"]] == [mine]


def test_history_disabled_gives_empty_conversations():
    body = _client(_tmp(), history=False).get(
        f"/bootstrap/{SESSION}/app_start").json()
    assert body["conversations"] == []
    assert body["capabilities"]["history"] is False


def test_history_enabled_is_reported():
    body = _client(_tmp()).get(f"/bootstrap/{SESSION}/app_start").json()
    assert body["capabilities"]["history"] is True


def test_reindex_capability_follows_admin_rights():
    tmp = _tmp()
    resp = _client(tmp, auth="proxy").get(
        f"/bootstrap/{SESSION}/app_start",
        headers={"X-Forwarded-Preferred-Username": "ivanov"},
    )
    # Кнопке переиндексации в интерфейсе неоткуда узнать про группы иначе.
    assert resp.json()["capabilities"]["reindex"] is False


def test_missing_index_does_not_fail_the_start():
    # Индекса нет — приложение обязано подняться и сказать об этом,
    # а не встретить пользователя пятисотой ошибкой.
    resp = _client(_tmp()).get(f"/bootstrap/{SESSION}/app_start")
    assert resp.status_code == 200, resp.status_code
    assert resp.json()["index"]["status"] == "no_index"


def test_models_are_listed():
    body = _client(_tmp()).get(f"/bootstrap/{SESSION}/app_start").json()
    # Экстрактивный бэкенд моделей не предлагает, но поле обязано быть:
    # клиент не должен проверять его наличие.
    assert isinstance(body["models"], list)


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
