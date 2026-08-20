"""Тесты диалогов организации. Запуск: python tests/test_org_conversations.py"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ragkb.history import HistoryStore

ORG = "acme"


def _tmp() -> Path:
    return Path(tempfile.mkdtemp(prefix="ragkb-orgconv-"))


def _client(tmp: Path, *, history: bool = True, org: dict | None = None,
            auth: str = "disabled"):
    """org=None — организация по умолчанию, org={} — не настроена."""
    from fastapi.testclient import TestClient

    from ragkb.api import create_app
    from ragkb.config import Config, OrganizationConfig

    cfg = Config()
    cfg.index_dir = str(tmp / "нет-индекса")
    cfg.auth.mode = auth
    cfg.history.enabled = history
    cfg.history.path = str(tmp / "history.sqlite3")
    cfg.organization = OrganizationConfig(
        **({"name": "Акме", "id": ORG} if org is None else org)
    )
    return TestClient(create_app(cfg), raise_server_exceptions=False)


def _url(org: str = ORG, **params) -> str:
    query = "&".join(f"{k}={v}" for k, v in params.items())
    return f"/organizations/{org}/chat_conversations" + (f"?{query}" if query else "")


def test_lists_own_conversations():
    tmp = _tmp()
    client = _client(tmp)
    store = HistoryStore(tmp / "history.sqlite3")
    mine = store.create_conversation("anonymous", "Мой")
    store.create_conversation("petrov", "Чужой")
    body = client.get(_url()).json()
    assert [c["id"] for c in body["conversations"]] == [mine]
    assert body["total"] == 1


def test_honours_limit_and_offset():
    tmp = _tmp()
    client = _client(tmp)
    store = HistoryStore(tmp / "history.sqlite3")
    for i in range(3):
        store.create_conversation("anonymous", f"Диалог {i}")
    body = client.get(_url(limit=1, offset=1)).json()
    assert len(body["conversations"]) == 1
    # total — общее число, а не размер страницы: иначе клиенту нечем
    # нарисовать постраничную навигацию.
    assert body["total"] == 3
    assert body["limit"] == 1
    assert body["offset"] == 1


def test_unknown_organization_gives_404():
    # Установка обслуживает одну организацию: чужой идентификатор в пути —
    # ошибка клиента, а не повод молча отдать свои диалоги.
    resp = _client(_tmp()).get(_url("другая"))
    assert resp.status_code == 404, resp.status_code
    # Проверяем текст, иначе тест не отличит «нет такой организации»
    # от «маршрута вообще не существует».
    assert resp.json()["detail"] == "Организация не найдена"


def test_unconfigured_organization_gives_404():
    resp = _client(_tmp(), org={}).get(_url())
    assert resp.status_code == 404, resp.status_code
    assert resp.json()["detail"] == "Организация не найдена"


def test_organization_can_be_addressed_by_name_when_id_is_empty():
    tmp = _tmp()
    client = _client(tmp, org={"name": "Акме"})
    assert client.get(_url("Акме")).status_code == 200


def test_disabled_history_gives_404():
    resp = _client(_tmp(), history=False).get(_url())
    assert resp.status_code == 404, resp.status_code
    assert resp.json()["detail"] == "История диалогов выключена"


def test_requires_authentication():
    assert _client(_tmp(), auth="proxy").get(_url()).status_code == 401


def test_default_consistency_is_strong():
    body = _client(_tmp()).get(_url()).json()
    assert body["consistency"] == "strong"


def test_unknown_consistency_is_refused():
    assert _client(_tmp()).get(_url(consistency="иногда")).status_code == 422


def test_eventual_serves_from_cache():
    tmp = _tmp()
    client = _client(tmp)
    store = HistoryStore(tmp / "history.sqlite3")
    store.create_conversation("anonymous", "Первый")
    first = client.get(_url(consistency="eventual")).json()
    assert first["cached"] is False
    store.create_conversation("anonymous", "Второй")
    again = client.get(_url(consistency="eventual")).json()
    # Ровно то, о чём просил клиент: отставание допустимо, зато без похода
    # в базу на каждое переключение вкладки.
    assert again["cached"] is True
    assert len(again["conversations"]) == 1


def test_strong_always_sees_fresh_data():
    tmp = _tmp()
    client = _client(tmp)
    store = HistoryStore(tmp / "history.sqlite3")
    store.create_conversation("anonymous", "Первый")
    client.get(_url(consistency="eventual"))
    store.create_conversation("anonymous", "Второй")
    body = client.get(_url()).json()
    assert len(body["conversations"]) == 2
    assert body["cached"] is False


def test_cache_is_not_shared_between_users():
    # Ключ кеша обязан включать пользователя: иначе первый зашедший
    # раздаст свои диалоги всем остальным.
    tmp = _tmp()
    client = _client(tmp, auth="proxy")
    store = HistoryStore(tmp / "history.sqlite3")
    store.create_conversation("ivanov", "Иванова")
    store.create_conversation("petrov", "Петрова")
    ivanov = client.get(
        _url(consistency="eventual"),
        headers={"X-Forwarded-Preferred-Username": "ivanov"},
    ).json()
    petrov = client.get(
        _url(consistency="eventual"),
        headers={"X-Forwarded-Preferred-Username": "petrov"},
    ).json()
    assert [c["title"] for c in ivanov["conversations"]] == ["Иванова"]
    assert [c["title"] for c in petrov["conversations"]] == ["Петрова"]


def test_cache_is_not_shared_between_pages():
    tmp = _tmp()
    client = _client(tmp)
    store = HistoryStore(tmp / "history.sqlite3")
    for i in range(3):
        store.create_conversation("anonymous", f"Диалог {i}")
    first = client.get(_url(consistency="eventual", limit=1, offset=0)).json()
    second = client.get(_url(consistency="eventual", limit=1, offset=1)).json()
    assert first["conversations"][0]["id"] != second["conversations"][0]["id"]


def test_limit_above_maximum_is_refused():
    assert _client(_tmp()).get(_url(limit=501)).status_code == 422


def test_negative_offset_is_refused():
    assert _client(_tmp()).get(_url(offset=-1)).status_code == 422


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
