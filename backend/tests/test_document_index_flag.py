"""Участие документа в поиске: что индексируется, а что только скачивается."""

from __future__ import annotations

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config as AlembicConfig
from fastapi.testclient import TestClient
from helpers import BACKEND_ROOT, make_app

from ragkb.core.config import Settings

POLICY = "# Политика\n\n## Отпуск\n\nЕжегодный отпуск — 28 календарных дней.\n"
TECH = "# Требования\n\n## Размер\n\nБаннер 100%×240 px, вес до 200 КБ.\n"
UNKNOWN_ID = "11111111-1111-4111-8111-111111111111"


@pytest.fixture
def sqlite_url(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    url = f"sqlite+aiosqlite:///{tmp_path / 'ragkb.sqlite3'}"
    config = AlembicConfig(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "migrations"))
    monkeypatch.setenv("RAGKB_DATABASE_URL", url)
    command.upgrade(config, "head")
    return url


def _cfg(tmp_path: Path, url: str = "") -> Settings:
    docs = tmp_path / "docs"
    docs.mkdir(exist_ok=True)
    cfg = Settings(docs_dir=str(docs), index_dir=str(tmp_path / "index"))
    cfg.store.backend = "memory"
    cfg.database_url = url
    cfg.logging.dir = str(tmp_path / "logs")
    return cfg


def _upload(client: TestClient, name: str, text: str, **params: str) -> dict:
    response = client.post(
        "/api/v1/admin/documents",
        params={"index": "false", **params},
        files={"file": (name, text.encode(), "text/markdown")},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _row(client: TestClient, name: str) -> dict:
    rows = client.get("/api/v1/admin/documents").json()["corpus"]
    return next(row for row in rows if row["name"] == name)


def _search(client: TestClient, query: str) -> list[dict]:
    response = client.post("/api/v1/search", json={"query": query, "top_k": 5})
    assert response.status_code == 200
    return response.json()["results"]


def test_excluded_document_never_reaches_the_index(tmp_path, sqlite_url):
    cfg = _cfg(tmp_path, sqlite_url)
    with TestClient(make_app(cfg)) as client:
        _upload(client, "policy.md", POLICY)
        _upload(client, "tech.md", TECH, index_enabled="false")
        assert client.get("/api/v1/admin/documents").json()["index"] == "no_index"

        assert client.post("/api/v1/index/rebuild").status_code == 200

        assert _search(client, "отпуск")
        hits = _search(client, "баннер 240")
        assert hits
        assert all("240 px" not in hit["text"] for hit in hits)
        assert all("tech.md" not in (hit["source"] or "") for hit in hits)
        assert _row(client, "tech.md")["index_enabled"] is False
        assert _row(client, "tech.md")["state"] == "excluded"
        assert _row(client, "tech.md")["indexed"] is False
        assert _row(client, "policy.md")["state"] == "indexed"


def test_toggle_applies_after_the_next_rebuild(tmp_path, sqlite_url):
    cfg = _cfg(tmp_path, sqlite_url)
    with TestClient(make_app(cfg)) as client:
        _upload(client, "tech.md", TECH)
        assert client.post("/api/v1/index/rebuild").status_code == 200
        assert _search(client, "баннер 240")

        row = _row(client, "tech.md")
        response = client.patch(
            f"/api/v1/documents/{row['document_id']}/index-permission",
            json={"index_enabled": False},
            headers={"x-request-id": "req-index"},
        )

        assert response.status_code == 200
        assert response.json() == {
            "document_id": row["document_id"],
            "index_enabled": False,
        }
        assert response.headers["cache-control"] == "no-store"
        assert _search(client, "баннер 240")

        assert client.post("/api/v1/index/rebuild").status_code == 200
        assert _search(client, "баннер 240") == []
        assert _row(client, "tech.md")["state"] == "excluded"

        back = client.patch(
            f"/api/v1/documents/{row['document_id']}/index-permission",
            json={"index_enabled": True},
        )
        assert back.json()["index_enabled"] is True
        assert client.post("/api/v1/index/rebuild").status_code == 200
        assert _search(client, "баннер 240")


def test_excluded_document_is_still_downloadable(tmp_path, sqlite_url):
    cfg = _cfg(tmp_path, sqlite_url)
    with TestClient(make_app(cfg)) as client:
        _upload(
            client,
            "tech.md",
            TECH,
            index_enabled="false",
            download_allowed="true",
        )
        row = _row(client, "tech.md")

        served = client.get(f"/api/v1/documents/{row['document_id']}/download")

        assert served.status_code == 200
        assert served.content == TECH.encode()


def test_refusals_keep_the_protocol(tmp_path, sqlite_url):
    cfg = _cfg(tmp_path, sqlite_url)
    with TestClient(make_app(cfg)) as client:
        unknown = client.patch(
            f"/api/v1/documents/{UNKNOWN_ID}/index-permission",
            json={"index_enabled": False},
        )
        assert unknown.status_code == 404
        assert unknown.headers["cache-control"] == "no-store"

        strict = client.patch(
            f"/api/v1/documents/{UNKNOWN_ID}/index-permission",
            json={"index_enabled": "нет"},
        )
        assert strict.status_code == 422

    without_db = _cfg(tmp_path)
    with TestClient(make_app(without_db)) as client:
        assert (
            client.patch(
                f"/api/v1/documents/{UNKNOWN_ID}/index-permission",
                json={"index_enabled": False},
            ).status_code
            == 400
        )
