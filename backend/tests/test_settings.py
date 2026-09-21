"""Страница настроек: описание полей, правка, сброс и расхождение с индексом.

Проверяется то, ради чего страница существует: значения применяются к живой
конфигурации и переживают перезапуск, секреты не утекают наружу, а расхождение
настроек с собранным индексом видно до того, как пользователь получит странный
ответ.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from helpers import corpus_names

from ragkb.core import settings as core
from ragkb.core.config import Settings
from ragkb.core.errors import InvalidRequest
from ragkb.core.index import ConfigIndex
from ragkb.core.pipeline import build_index
from ragkb.core.settings import FIELDS, GROUP_ORDER
from ragkb.services.settings import SettingsService


def _service(
    cfg: Settings,
    invalidated: list[int] | None = None,
    *,
    index: bool = False,
) -> SettingsService:
    """Сервис настроек; с `index=True` — как в приложении, со сведениями об индексе."""
    calls = invalidated if invalidated is not None else []
    engine = ConfigIndex(cfg, lambda: pytest.fail("движок для настроек не нужен"))
    return SettingsService(cfg, lambda: calls.append(1), index=engine if index else None)


# ------------------------------------------------------------- описание полей


def test_describe_covers_every_group(cfg):
    payload = _service(cfg).describe()

    titles = [group["title"] for group in payload["groups"]]
    assert titles == [title for title in GROUP_ORDER if title in titles]
    paths = {field["path"] for group in payload["groups"] for field in group["fields"]}
    assert paths == {field.path for field in FIELDS}
    assert payload["file"].endswith("settings.json")


def test_describe_marks_source_of_values(cfg, monkeypatch):
    payload = _service(cfg).describe()
    by_path = {
        field["path"]: field for group in payload["groups"] for field in group["fields"]
    }

    assert by_path["retrieval.top_k"]["source"] == "default"
    monkeypatch.setenv("RAGKB_EMBEDDING_MODEL", "bge-m3")
    fresh = Settings()
    payload = _service(fresh).describe()
    by_path = {
        field["path"]: field for group in payload["groups"] for field in group["fields"]
    }
    assert by_path["embedding.model"]["source"] == "env"
    assert by_path["embedding.model"]["value"] == "bge-m3"


def test_describe_keeps_secrets_masked(cfg):
    cfg.llm.api_key = "sk-очень-секретный"
    payload = _service(cfg).describe()
    field = next(
        item
        for group in payload["groups"]
        for item in group["fields"]
        if item["path"] == "llm.api_key"
    )

    assert field["secret"] is True
    assert field["value"] == "***"
    assert "sk-" not in json.dumps(payload, ensure_ascii=False)


def test_readonly_shows_where_data_lives(cfg):
    payload = _service(cfg).describe()
    paths = {item["path"] for item in payload["readonly"]}

    assert {"docs_dir", "index_dir", "settings_file", "database_url"} <= paths


def test_database_password_is_hidden(cfg):
    cfg.database_url = "postgresql+asyncpg://ragkb:secret@db:5432/ragkb"

    payload = _service(cfg).describe()
    value = next(item["value"] for item in payload["readonly"] if item["path"] == "database_url")

    assert value == "postgresql+asyncpg://ragkb:***@db:5432/ragkb"


# ------------------------------------------------------------------- правка


def test_update_applies_value_and_persists(cfg):
    invalidated: list[int] = []
    service = _service(cfg, invalidated)

    payload = service.update({"retrieval.top_k": 9, "retrieval.use_mmr": False})

    assert cfg.retrieval.top_k == 9
    assert cfg.retrieval.use_mmr is False
    assert invalidated, "движок должен быть сброшен после правки"
    assert sorted(payload["changed"]) == ["retrieval.top_k", "retrieval.use_mmr"]
    stored = json.loads(Path(cfg.settings_file).read_text(encoding="utf-8"))
    assert stored == {"retrieval.top_k": 9, "retrieval.use_mmr": False}


def test_saved_settings_survive_restart(cfg):
    _service(cfg).update({"retrieval.top_k": 11, "organization.name": "Acme"})

    restarted = Settings()
    restarted.settings_file = cfg.settings_file
    applied = core.apply_overrides(restarted, core.read_overrides(cfg.settings_file))

    assert sorted(applied) == ["organization.name", "retrieval.top_k"]
    assert restarted.retrieval.top_k == 11
    assert restarted.organization.name == "Acme"


def test_update_reports_changed_sources(cfg):
    service = _service(cfg)

    payload = service.update({"retrieval.min_score": 0.35})

    field = next(
        item
        for group in payload["groups"]
        for item in group["fields"]
        if item["path"] == "retrieval.min_score"
    )
    assert field["source"] == "settings"
    assert field["value"] == 0.35
    assert payload["overridden"] == ["retrieval.min_score"]


def test_update_skips_empty_secret(cfg):
    service = _service(cfg)
    service.update({"llm.api_key": "sk-1"})

    service.update({"llm.api_key": "***"})

    assert cfg.llm.api_key == "sk-1"


def test_reset_returns_value_from_environment(cfg, monkeypatch):
    monkeypatch.setenv("RAGKB_EMBEDDING_MODEL", "bge-m3")
    fresh = Settings()
    fresh.settings_file = cfg.settings_file
    service = _service(fresh)
    service.update({"embedding.model": "другая:модель"})
    assert fresh.embedding.model == "другая:модель"

    payload = service.update({}, reset=["embedding.model"])

    assert fresh.embedding.model == "bge-m3"
    assert "embedding.model" not in core.read_overrides(fresh.settings_file)
    field = next(
        item
        for group in payload["groups"]
        for item in group["fields"]
        if item["path"] == "embedding.model"
    )
    assert field["source"] == "env"


def test_unknown_field_is_rejected(cfg):
    with pytest.raises(InvalidRequest) as exc:
        _service(cfg).update({"retrieval.нет_такого": 1})
    assert "retrieval.нет_такого" in exc.value.detail


def test_out_of_range_number_is_rejected(cfg):
    with pytest.raises(InvalidRequest) as exc:
        _service(cfg).update({"retrieval.top_k": 999})
    assert "Фрагментов в ответ" in exc.value.detail


def test_wrong_type_is_rejected(cfg):
    with pytest.raises(InvalidRequest) as exc:
        _service(cfg).update({"retrieval.top_k": "много"})
    assert "ожидается число" in exc.value.detail


def test_select_value_is_checked(cfg):
    with pytest.raises(InvalidRequest) as exc:
        _service(cfg).update({"embedding.backend": "tfidf"})
    assert "ollama" in exc.value.detail


def test_requirements_are_reported(indexed):
    """Правка поля, влияющего на индекс, требует пересборки — если он собран."""
    service = _service(indexed, index=True)

    reindex = service.update({"embedding.model": "qwen3-embedding:8b"})
    restart = service.update({"llm.backend": "ollama"})
    none = service.update({"retrieval.top_k": 4})

    assert reindex["requirements"]["reindex"] is True
    assert restart["requirements"]["restart"] is True
    assert none["requirements"] == {"reindex": False, "restart": False}


def test_reindex_not_required_without_index(cfg):
    """Пересобирать нечего: страница сама предложит собрать индекс."""
    payload = _service(cfg, index=True).update({"embedding.model": "qwen3-embedding:8b"})

    assert payload["index"]["status"] == "no_index"
    assert payload["requirements"]["reindex"] is False


def test_reverting_to_built_settings_needs_no_reindex(indexed):
    service = _service(indexed, index=True)
    service.update({"chunking.size": 400})

    reverted = service.update({}, reset=["chunking.size"])

    assert reverted["index"]["stale"] is False
    assert reverted["requirements"]["reindex"] is False


def test_full_catalog_patch_is_accepted(cfg):
    """Форма может отправить все поля сразу — это нормальный сценарий сохранения."""
    patch = {field.path: core.value_at(cfg, field.path) for field in FIELDS}

    payload = _service(cfg).update(patch)

    # Значения не изменились — пересборка и перезапуск не нужны.
    assert payload["requirements"] == {"reindex": False, "restart": False}
    assert payload["changed"] == []
    # Пустой секрет не сохраняется: пустая строка в форме означает «не менять».
    expected = sorted(field.path for field in FIELDS if not field.secret)
    assert sorted(payload["overridden"]) == expected


# --------------------------------------------------- расхождение с индексом


def test_index_state_reports_drift_after_embedder_change(indexed):
    service = _service(indexed, index=True)

    before = service.describe()["index"]
    service.update({"embedding.fake_dim": 64})
    after = service.describe()["index"]

    assert before["status"] == "ok"
    assert before["stale"] is False
    assert after["stale"] is True
    assert any("пересборка" in warning for warning in after["warnings"])


def test_index_state_reports_drift_after_chunking_change(cfg):
    build_index(cfg, corpus_names(cfg))
    service = _service(cfg, index=True)

    service.update({"chunking.size": 400})
    index = service.describe()["index"]

    assert index["stale"] is True
    assert any("чанком" in warning for warning in index["warnings"])


def test_index_state_without_index(cfg):
    index = _service(cfg, index=True).describe()["index"]

    assert index["status"] == "no_index"
    assert "detail" in index


# ---------------------------------------------------------------------- API


def test_settings_api_returns_fields(client):
    body = client.get("/api/v1/admin/settings").json()

    assert body["groups"]
    assert client.get("/api/v1/admin/settings").headers.get("set-cookie") is None


def test_settings_api_applies_patch(client, cfg):
    response = client.put(
        "/api/v1/admin/settings", json={"values": {"retrieval.top_k": 7}}
    )

    assert response.status_code == 200
    assert cfg.retrieval.top_k == 7
    assert response.json()["changed"] == ["retrieval.top_k"]


def test_settings_api_rejects_unknown_field(client):
    response = client.put("/api/v1/admin/settings", json={"values": {"нет.такого": 1}})

    assert response.status_code == 400
    assert "Неизвестные настройки" in response.json()["detail"]


def test_settings_api_reset(client, cfg):
    client.put("/api/v1/admin/settings", json={"values": {"retrieval.top_k": 7}})

    response = client.put("/api/v1/admin/settings", json={"reset": ["retrieval.top_k"]})

    assert response.status_code == 200
    assert cfg.retrieval.top_k == 5
    assert core.read_overrides(cfg.settings_file) == {}
