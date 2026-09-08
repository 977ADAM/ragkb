import asyncio
import os
from datetime import datetime, timezone
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config as AlembicConfig
from fastapi.testclient import TestClient
from helpers import BACKEND_ROOT

from ragkb.core.config import Settings
from ragkb.core.database import make_engine, make_session_factory
from ragkb.core.errors import EngineUnavailable, InvalidRequest, NotFound, PayloadTooLarge
from ragkb.core.pipeline import RAGPipeline, build_index
from ragkb.db.repos.auth import PostgresAccounts
from ragkb.main import create_app
from ragkb.services.auth import hash_password
from ragkb.services.documents import MAX_UPLOAD_BYTES, DocumentsService


def make_cfg(tmp_path: Path) -> Settings:
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "policy.md").write_text(
        "# Политика\n\n## Отпуск\n\nЕжегодный отпуск составляет 28 календарных дней.\n",
        encoding="utf-8",
    )
    cfg = Settings(docs_dir=str(docs), index_dir=str(tmp_path / "index"))
    cfg.store.backend = "numpy"
    return cfg


def make_service(cfg: Settings) -> DocumentsService:
    def get_engine():
        try:
            return RAGPipeline(cfg)
        except (FileNotFoundError, ValueError) as exc:
            raise EngineUnavailable(str(exc)) from exc

    return DocumentsService(cfg, get_engine, lambda: None)


def test_list_after_build(tmp_path):
    cfg = make_cfg(tmp_path)
    build_index(cfg)
    svc = make_service(cfg)
    body = svc.list_documents()
    assert body["index"] == "ok"
    assert body["built_at"] is not None
    assert len(body["corpus"]) == 1
    row = body["corpus"][0]
    assert row["name"] == "policy.md"
    assert row["indexed"] is True
    assert row["state"] == "indexed"
    assert row["chunks"] >= 1
    assert body["summary"]["corpus_files"] == 1
    assert body["orphans"] == []


def test_list_new_file_is_new(tmp_path):
    cfg = make_cfg(tmp_path)
    build_index(cfg)
    (Path(cfg.docs_dir) / "fresh.md").write_text("# Новый\n\nТекст.\n", encoding="utf-8")
    body = make_service(cfg).list_documents()
    by_name = {r["name"]: r for r in body["corpus"]}
    assert by_name["fresh.md"]["state"] == "new"
    assert by_name["fresh.md"]["indexed"] is False


def test_list_stale_when_mtime_newer(tmp_path):
    cfg = make_cfg(tmp_path)
    build_index(cfg)
    target = Path(cfg.docs_dir) / "policy.md"
    future = datetime.now(timezone.utc).timestamp() + 3600
    os.utime(target, (future, future))
    body = make_service(cfg).list_documents()
    row = next(r for r in body["corpus"] if r["name"] == "policy.md")
    assert row["state"] == "stale"


def test_list_orphan_when_file_removed(tmp_path):
    cfg = make_cfg(tmp_path)
    build_index(cfg)
    (Path(cfg.docs_dir) / "policy.md").unlink()
    body = make_service(cfg).list_documents()
    assert len(body["orphans"]) == 1
    assert body["orphans"][0]["source"].endswith("policy.md")


def test_list_no_index(tmp_path):
    cfg = make_cfg(tmp_path)  # индекс не собран
    body = make_service(cfg).list_documents()
    assert body["index"] == "no_index"
    assert body["built_at"] is None
    assert body["orphans"] == [] and body["skipped"] == []
    assert body["corpus"][0]["state"] is None


def test_upload_saves_file_and_reindexes(tmp_path):
    cfg = make_cfg(tmp_path)
    build_index(cfg)
    svc = make_service(cfg)
    report = svc.upload("new.md", "# Новый\n\nПравило про отпуск: 28 дней.\n".encode())
    assert report["files"] >= 1
    assert (Path(cfg.docs_dir) / "new.md").exists()
    body = svc.list_documents()
    assert len(body["corpus"]) == 2
    assert all(r["indexed"] for r in body["corpus"])


def test_upload_rejects_bad_extension(tmp_path):
    cfg = make_cfg(tmp_path)
    svc = make_service(cfg)
    with pytest.raises(InvalidRequest):
        svc.upload("evil.exe", b"x" * 10)


def test_upload_rejects_hidden_name(tmp_path):
    cfg = make_cfg(tmp_path)
    svc = make_service(cfg)
    with pytest.raises(InvalidRequest):
        svc.upload(".env", b"SECRET=1\n")


def test_upload_rolls_back_when_corpus_empty(tmp_path, monkeypatch):
    cfg = make_cfg(tmp_path)
    (Path(cfg.docs_dir) / "policy.md").unlink()
    svc = make_service(cfg)
    # файл с расширением, но без текста — build_index упадёт целиком
    with pytest.raises(InvalidRequest):
        svc.upload("scan.pdf", b"%PDF-1.4 no text layer")
    assert not (Path(cfg.docs_dir) / "scan.pdf").exists()


def test_upload_size_limit(tmp_path):
    cfg = make_cfg(tmp_path)
    svc = make_service(cfg)
    with pytest.raises(PayloadTooLarge):
        svc.upload("big.md", b"a" * (MAX_UPLOAD_BYTES + 1))


def test_delete_removes_file_and_index_entry(tmp_path):
    cfg = make_cfg(tmp_path)
    build_index(cfg)
    (Path(cfg.docs_dir) / "policy.md").write_text(
        "# A\n\n## B\n\n" + "x" * 2000 + "\n", encoding="utf-8"
    )
    # второй документ, чтобы после удаления корпус не опустел
    (Path(cfg.docs_dir) / "keep.md").write_text("# Keep\n\nТекст для чанка.\n", encoding="utf-8")
    build_index(cfg)
    svc = make_service(cfg)
    svc.delete("policy.md")
    assert not (Path(cfg.docs_dir) / "policy.md").exists()
    body = svc.list_documents()
    names = {r["name"] for r in body["corpus"]}
    assert "policy.md" not in names and "keep.md" in names


def test_delete_missing_file_is_404(tmp_path):
    cfg = make_cfg(tmp_path)
    build_index(cfg)
    with pytest.raises(NotFound):
        make_service(cfg).delete("nope.md")


def test_delete_last_doc_clears_index(tmp_path):
    cfg = make_cfg(tmp_path)
    build_index(cfg)
    make_service(cfg).delete("policy.md")
    body = make_service(cfg).list_documents()
    assert body["index"] == "no_index"


def test_delete_on_chroma_is_point_removal(tmp_path):
    pytest.importorskip("chromadb")
    cfg = make_cfg(tmp_path)
    cfg.store.backend = "chroma"
    build_index(cfg)
    (Path(cfg.docs_dir) / "keep.md").write_text("# Keep\n\nТекст.\n", encoding="utf-8")
    build_index(cfg)
    make_service(cfg).delete("keep.md")
    body = make_service(cfg).list_documents()
    assert all(r["name"] != "keep.md" for r in body["corpus"])


def test_delete_last_doc_clears_chroma_index(tmp_path):
    pytest.importorskip("chromadb")
    cfg = make_cfg(tmp_path)
    cfg.store.backend = "chroma"
    build_index(cfg)
    make_service(cfg).delete("policy.md")
    body = make_service(cfg).list_documents()
    assert body["index"] == "no_index"


def _migrate_sqlite(url: str, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = AlembicConfig(str(BACKEND_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_ROOT / "migrations"))
    monkeypatch.setenv("RAGKB_DATABASE_URL", url)
    command.upgrade(cfg, "head")


async def _seed_admin_and_user(url: str) -> None:
    engine = make_engine(url)
    store = PostgresAccounts(make_session_factory(engine))
    await store.ready()
    await store.create_user("ada", hash_password("password1"), role="admin")
    await store.create_user("bob", hash_password("password1"), role="user")
    await engine.dispose()


def _session_client_cfg(tmp_path: Path, url: str) -> Settings:
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "policy.md").write_text("# Политика\n\nТекст про отпуск: 28 дней.\n", encoding="utf-8")
    cfg = Settings(
        docs_dir=str(docs),
        index_dir=str(tmp_path / "index"),
        organization=Settings.OrganizationConfig(name="Acme", id="acme"),
    )
    cfg.store.backend = "numpy"
    cfg.database_url = url
    cfg.auth.mode = "session"
    cfg.history.enabled = True
    cfg.logging.dir = str(tmp_path / "logs")
    return cfg


def _signin(client: TestClient, username: str) -> None:
    res = client.post(
        "/api/v1/auths/signin",
        json={"username": username, "password": "password1"},
    )
    assert res.status_code == 200


@pytest.fixture
def sqlite_url(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    db = tmp_path / "ragkb.sqlite3"
    url = f"sqlite+aiosqlite:///{db}"
    _migrate_sqlite(url, monkeypatch)
    asyncio.run(_seed_admin_and_user(url))
    return url


def test_non_admin_forbidden_on_documents(tmp_path, sqlite_url):
    cfg = _session_client_cfg(tmp_path, sqlite_url)
    with TestClient(create_app(cfg)) as client:
        _signin(client, "bob")
        assert client.get("/api/v1/admin/documents").status_code == 403
        assert client.post(
            "/api/v1/admin/documents", files={"file": ("x.md", b"# X", "text/markdown")}
        ).status_code == 403
        assert client.delete("/api/v1/admin/documents/x.md").status_code == 403


def test_admin_gets_document_list(tmp_path, sqlite_url):
    cfg = _session_client_cfg(tmp_path, sqlite_url)
    with TestClient(create_app(cfg)) as client:
        _signin(client, "ada")
        body = client.get("/api/v1/admin/documents").json()
        assert body["index"] == "no_index"
        assert body["corpus"][0]["name"] == "policy.md"


def test_admin_upload_and_list(tmp_path, sqlite_url):
    cfg = _session_client_cfg(tmp_path, sqlite_url)
    with TestClient(create_app(cfg)) as client:
        _signin(client, "ada")
        res = client.post(
            "/api/v1/admin/documents",
            files={"file": ("new.md", "# Новый\n\nПравило: 28 дней.\n".encode(), "text/markdown")},
        )
        assert res.status_code == 200
        assert res.json()["chunks"] >= 1
        body = client.get("/api/v1/admin/documents").json()
        assert body["index"] == "ok"
        assert len(body["corpus"]) == 2


def test_admin_upload_bad_extension_is_400(tmp_path, sqlite_url):
    cfg = _session_client_cfg(tmp_path, sqlite_url)
    with TestClient(create_app(cfg)) as client:
        _signin(client, "ada")
        res = client.post(
            "/api/v1/admin/documents",
            files={"file": ("evil.exe", b"x", "application/octet-stream")},
        )
        assert res.status_code == 400


def test_admin_upload_too_large_is_413(tmp_path, sqlite_url, monkeypatch):
    import ragkb.services.documents as documents_module

    monkeypatch.setattr(documents_module, "MAX_UPLOAD_BYTES", 10)
    cfg = _session_client_cfg(tmp_path, sqlite_url)
    with TestClient(create_app(cfg)) as client:
        _signin(client, "ada")
        res = client.post(
            "/api/v1/admin/documents",
            files={"file": ("big.md", b"a" * 20, "text/markdown")},
        )
        assert res.status_code == 413


def test_admin_delete(tmp_path, sqlite_url):
    cfg = _session_client_cfg(tmp_path, sqlite_url)
    with TestClient(create_app(cfg)) as client:
        _signin(client, "ada")
        client.post(
            "/api/v1/admin/documents",
            files={"file": ("new.md", "# N\n\nТекст.\n".encode(), "text/markdown")},
        )
        res = client.delete("/api/v1/admin/documents/new.md")
        assert res.status_code == 204
        assert client.delete("/api/v1/admin/documents/new.md").status_code == 404


def test_request_form_wrapper_sets_max_part_size(monkeypatch):
    from starlette.requests import Request as StarletteRequest

    import ragkb.api.multipart as multipart

    seen: dict = {}

    def fake(self, *args, **kwargs):
        seen.update(kwargs)
        return "ok"

    monkeypatch.setattr(StarletteRequest, "form", fake)
    multipart.raise_multipart_part_limit()
    assert StarletteRequest.form(object()) == "ok"
    assert seen["max_part_size"] == multipart.MULTIPART_MAX_PART_SIZE
