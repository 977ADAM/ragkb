"""Документы корпуса: загрузка через интерфейс, удаление и состояние.

Главное правило проверяется здесь же: каталог документов не обходится.
Документ попадает в базу знаний только загрузкой через интерфейс (запись в
реестре), а файл, положенный в каталог мимо, не индексируется и в списке не
показывается. Без реестра (нет базы) операции недоступны.
"""
from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config as AlembicConfig
from fastapi.testclient import TestClient
from helpers import BACKEND_ROOT, MemoryRegistry, make_app

from ragkb.core.config import Settings
from ragkb.core.errors import EngineUnavailable, InvalidRequest, NotFound, PayloadTooLarge
from ragkb.core.index import ConfigIndex
from ragkb.core.pipeline import RagChain, build_index
from ragkb.domain.entities import ORIGIN_UI
from ragkb.services.documents import DocumentsService
from ragkb.services.index import IndexService

POLICY = "# Политика\n\n## Отпуск\n\nЕжегодный отпуск составляет 28 календарных дней.\n"


def make_cfg(tmp_path: Path) -> Settings:
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "policy.md").write_text(POLICY, encoding="utf-8")
    cfg = Settings(docs_dir=str(docs), index_dir=str(tmp_path / "index"))
    cfg.store.backend = "memory"
    return cfg


def registry_with(cfg: Settings, *names: str) -> MemoryRegistry:
    """Реестр, в котором уже лежат файлы из каталога (как после загрузки)."""
    return MemoryRegistry().add(cfg, *(names or ("policy.md",)))


def make_service(cfg: Settings, registry=None, invalidate=None) -> DocumentsService:
    def get_engine():
        try:
            return RagChain(cfg)
        except (FileNotFoundError, ValueError) as exc:
            raise EngineUnavailable(str(exc)) from exc

    return DocumentsService(
        cfg,
        ConfigIndex(cfg, get_engine),
        invalidate or (lambda: None),
        registry,
    )


# ------------------------------------------------------- без реестра нельзя


async def test_list_without_registry_reports_it_is_off(tmp_path):
    cfg = make_cfg(tmp_path)

    body = await make_service(cfg).list_documents()

    assert body["registry"] == "off"
    assert body["corpus"] == []
    assert body["summary"]["corpus_files"] == 0


async def test_upload_without_registry_is_rejected(tmp_path):
    cfg = make_cfg(tmp_path)

    with pytest.raises(InvalidRequest) as exc:
        await make_service(cfg).upload("new.md", b"# N\n", index=False)

    assert "RAGKB_DATABASE_URL" in exc.value.detail


async def test_delete_without_registry_is_rejected(tmp_path):
    cfg = make_cfg(tmp_path)

    with pytest.raises(InvalidRequest):
        await make_service(cfg).delete("policy.md")


def test_rebuild_without_registry_is_rejected(tmp_path):
    cfg = make_cfg(tmp_path)
    service = IndexService(ConfigIndex(cfg, lambda: None), lambda: None)

    with pytest.raises(InvalidRequest) as exc:
        asyncio.run(service.rebuild())

    assert "RAGKB_DATABASE_URL" in exc.value.detail


# ----------------------------------------------------------- список корпуса


async def test_list_after_upload_and_index(tmp_path):
    cfg = make_cfg(tmp_path)
    registry = MemoryRegistry()
    svc = make_service(cfg, registry)
    await svc.upload("policy.md", POLICY.encode(), "ada")

    body = await svc.list_documents()

    assert body["index"] == "ok"
    assert body["built_at"] is not None
    assert body["registry"] == "on"
    row = body["corpus"][0]
    assert row["name"] == "policy.md"
    assert row["indexed"] is True
    assert row["state"] == "indexed"
    assert row["origin"] == ORIGIN_UI
    assert row["uploaded_by"] == "ada"
    assert row["chunks"] >= 1
    assert body["summary"] == {"corpus_files": 1, "indexed_docs": 1, "chunks": row["chunks"]}


async def test_file_outside_registry_is_invisible(tmp_path):
    """Файл, положенный в каталог мимо интерфейса, в корпус не попадает."""
    cfg = make_cfg(tmp_path)
    (Path(cfg.docs_dir) / "secret.md").write_text(
        "# Секрет\n\nКод доступа к хранилищу: КАРАНДАШ-77.\n", encoding="utf-8"
    )
    registry = registry_with(cfg, "policy.md")
    build_index(cfg, registry.index_names())

    body = await make_service(cfg, registry).list_documents()
    hits = RagChain(cfg).search("код доступа к хранилищу", top_k=5)

    assert [row["name"] for row in body["corpus"]] == ["policy.md"]
    assert all("КАРАНДАШ" not in hit.text for hit in hits)


async def test_upload_without_index_is_new(tmp_path):
    cfg = make_cfg(tmp_path)
    registry = registry_with(cfg)
    build_index(cfg, registry.index_names())
    svc = make_service(cfg, registry)

    result = await svc.upload("new.md", "# Новый\n\nТекст.\n".encode(), index=False)

    body = await svc.list_documents()
    row = next(r for r in body["corpus"] if r["name"] == "new.md")
    assert result["indexed"] is False
    assert row["state"] == "new"
    assert row["indexed"] is False


async def test_file_removed_behind_interface_is_missing(tmp_path):
    cfg = make_cfg(tmp_path)
    registry = registry_with(cfg)
    build_index(cfg, registry.index_names())
    (Path(cfg.docs_dir) / "policy.md").unlink()

    body = await make_service(cfg, registry).list_documents()

    row = body["corpus"][0]
    assert row["state"] == "missing"
    assert row["indexed"] is True  # в индексе он ещё есть


async def test_changed_file_is_stale(tmp_path):
    cfg = make_cfg(tmp_path)
    registry = registry_with(cfg)
    build_index(cfg, registry.index_names())
    target = Path(cfg.docs_dir) / "policy.md"
    future = datetime.now(timezone.utc).timestamp() + 3600
    os.utime(target, (future, future))

    body = await make_service(cfg, registry).list_documents()

    assert body["corpus"][0]["state"] == "stale"


async def test_list_without_index(tmp_path):
    cfg = make_cfg(tmp_path)
    registry = registry_with(cfg)

    body = await make_service(cfg, registry).list_documents()

    assert body["index"] == "no_index"
    assert body["corpus"][0]["state"] is None
    assert body["corpus"][0]["indexed"] is False


# ---------------------------------------------------------------- загрузка


async def test_upload_saves_file_and_indexes(tmp_path):
    cfg = make_cfg(tmp_path)
    registry = MemoryRegistry()
    dropped: list[bool] = []
    svc = make_service(cfg, registry, invalidate=lambda: dropped.append(True))

    result = await svc.upload("new.md", "# Новый\n\nПравило: 28 дней.\n".encode(), "ada")

    assert result["indexed"] is True
    assert result["files"] == 1
    assert result["chunks"] >= 1
    assert dropped, "кеш движка не сброшен: поиск не увидит загруженный документ"
    assert (Path(cfg.docs_dir) / "new.md").is_file()
    row = registry.rows["new.md"]
    assert row.origin == ORIGIN_UI
    assert row.size > 0 and len(row.sha256) == 64


async def test_upload_rejects_bad_extension(tmp_path):
    cfg = make_cfg(tmp_path)
    with pytest.raises(InvalidRequest):
        await make_service(cfg, MemoryRegistry()).upload("evil.exe", b"x", index=False)


async def test_upload_rejects_hidden_name(tmp_path):
    cfg = make_cfg(tmp_path)
    with pytest.raises(InvalidRequest):
        await make_service(cfg, MemoryRegistry()).upload(".secret.md", b"x", index=False)


async def test_upload_size_limit(tmp_path, monkeypatch):
    import ragkb.services.documents as documents_module

    monkeypatch.setattr(documents_module, "MAX_UPLOAD_BYTES", 10)
    cfg = make_cfg(tmp_path)
    with pytest.raises(PayloadTooLarge):
        await make_service(cfg, MemoryRegistry()).upload("big.md", b"a" * 20, index=False)


async def test_upload_rolls_back_when_text_is_empty(tmp_path):
    """Нечитаемый документ не остаётся ни файлом, ни записью в реестре."""
    cfg = make_cfg(tmp_path)
    registry = MemoryRegistry()
    svc = make_service(cfg, registry)

    with pytest.raises(InvalidRequest):
        await svc.upload("scan.pdf", b"not a pdf at all")

    assert "scan.pdf" not in registry.rows
    assert not (Path(cfg.docs_dir) / "scan.pdf").exists()


# ---------------------------------------------------------------- удаление


async def test_delete_removes_file_registry_row_and_index_entry(tmp_path):
    cfg = make_cfg(tmp_path)
    registry = MemoryRegistry()
    svc = make_service(cfg, registry)
    await svc.upload("policy.md", POLICY.encode())
    await svc.upload("keep.md", "# Keep\n\nДругой текст.\n".encode())

    await svc.delete("policy.md")

    body = await svc.list_documents()
    assert "policy.md" not in registry.rows
    assert not (Path(cfg.docs_dir) / "policy.md").exists()
    assert [row["name"] for row in body["corpus"]] == ["keep.md"]
    assert body["index"] == "ok"
    assert all("28 календарных" not in hit.text for hit in RagChain(cfg).search("отпуск", 5))


async def test_delete_last_document_clears_index(tmp_path):
    cfg = make_cfg(tmp_path)
    registry = MemoryRegistry()
    svc = make_service(cfg, registry)
    await svc.upload("policy.md", POLICY.encode())

    await svc.delete("policy.md")

    body = await svc.list_documents()
    assert body["index"] == "no_index"
    assert body["corpus"] == []


async def test_delete_missing_file_is_404(tmp_path):
    cfg = make_cfg(tmp_path)
    registry = registry_with(cfg)

    with pytest.raises(NotFound):
        await make_service(cfg, registry).delete("нет-такого.md")


async def test_delete_rejects_path_outside_corpus(tmp_path):
    cfg = make_cfg(tmp_path)
    registry = registry_with(cfg)

    with pytest.raises((InvalidRequest, NotFound)):
        await make_service(cfg, registry).delete("../outside.md")


# ------------------------------------------------------------- индексация


def test_build_index_without_documents_explains_what_to_do(tmp_path):
    cfg = make_cfg(tmp_path)

    with pytest.raises(ValueError) as exc:
        build_index(cfg, frozenset())

    assert "загрузите их на странице" in str(exc.value).lower()


def test_build_index_skips_missing_registry_rows(tmp_path):
    cfg = make_cfg(tmp_path)
    (Path(cfg.docs_dir) / "policy.md").unlink()

    with pytest.raises(ValueError) as exc:
        build_index(cfg, frozenset({"policy.md"}))

    assert "файл не найден" in str(exc.value)


# ------------------------------------------------------------ публичный API


def _migrate_sqlite(url: str, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = AlembicConfig(str(BACKEND_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_ROOT / "migrations"))
    monkeypatch.setenv("RAGKB_DATABASE_URL", url)
    command.upgrade(cfg, "head")


def _public_client_cfg(tmp_path: Path, url: str) -> Settings:
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "policy.md").write_text(POLICY, encoding="utf-8")
    cfg = Settings(
        docs_dir=str(docs),
        index_dir=str(tmp_path / "index"),
        organization=Settings.OrganizationConfig(name="Acme", id="acme"),
    )
    cfg.store.backend = "memory"
    cfg.database_url = url
    cfg.logging.dir = str(tmp_path / "logs")
    return cfg


@pytest.fixture
def sqlite_url(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    db = tmp_path / "ragkb.sqlite3"
    url = f"sqlite+aiosqlite:///{db}"
    _migrate_sqlite(url, monkeypatch)
    return url


def test_public_list_is_empty_until_upload(tmp_path, sqlite_url):
    """Файл в каталоге сам в корпус не попадает: нужна загрузка."""
    cfg = _public_client_cfg(tmp_path, sqlite_url)
    with TestClient(make_app(cfg)) as client:
        body = client.get("/api/v1/admin/documents").json()
        assert body["registry"] == "on"
        assert body["index"] == "no_index"
        assert body["corpus"] == []


def test_public_upload_and_list(tmp_path, sqlite_url):
    cfg = _public_client_cfg(tmp_path, sqlite_url)
    with TestClient(make_app(cfg)) as client:
        res = client.post(
            "/api/v1/admin/documents",
            files={"file": ("new.md", "# Новый\n\nПравило: 28 дней.\n".encode(), "text/markdown")},
        )
        assert res.status_code == 200
        assert res.json()["chunks"] >= 1

        body = client.get("/api/v1/admin/documents").json()
        assert body["index"] == "ok"
        assert [row["name"] for row in body["corpus"]] == ["new.md"]
        assert body["corpus"][0]["state"] == "indexed"
        assert body["corpus"][0]["origin"] == ORIGIN_UI


def test_public_accept_route_is_gone(tmp_path, sqlite_url):
    """Приёма файлов из каталога больше нет: корпус наполняется загрузкой.

    404 или 405 — оба означают, что маршрута нет: 405 приходит, потому что
    путь совпал с удалением документа `/documents/{name}`.
    """
    cfg = _public_client_cfg(tmp_path, sqlite_url)
    with TestClient(make_app(cfg)) as client:
        res = client.post("/api/v1/admin/documents/accept", json={"names": ["policy.md"]})
        assert res.status_code in {404, 405}


def test_public_rebuild_with_empty_corpus_is_400(tmp_path, sqlite_url):
    cfg = _public_client_cfg(tmp_path, sqlite_url)
    with TestClient(make_app(cfg)) as client:
        res = client.post("/api/v1/index/rebuild")
        assert res.status_code == 400
        assert "загрузите" in res.json()["detail"].lower()


def test_public_batch_upload_uses_single_rebuild(tmp_path, sqlite_url):
    """Очередь загрузки не индексирует каждый файл по отдельности."""
    cfg = _public_client_cfg(tmp_path, sqlite_url)
    with TestClient(make_app(cfg)) as client:
        for name in ("one.md", "two.md"):
            res = client.post(
                "/api/v1/admin/documents",
                params={"index": "false"},
                files={"file": (name, f"# {name}\n\nТекст.\n".encode(), "text/markdown")},
            )
            assert res.status_code == 200
            assert res.json()["indexed"] is False

        assert client.get("/api/v1/admin/documents").json()["index"] == "no_index"

        rebuilt = client.post("/api/v1/index/rebuild")
        assert rebuilt.status_code == 200
        assert rebuilt.json()["files"] == 2

        after = client.get("/api/v1/admin/documents").json()
        assert {r["name"]: r["state"] for r in after["corpus"]} == {
            "one.md": "indexed",
            "two.md": "indexed",
        }


def test_public_upload_bad_extension_is_400(tmp_path, sqlite_url):
    cfg = _public_client_cfg(tmp_path, sqlite_url)
    with TestClient(make_app(cfg)) as client:
        res = client.post(
            "/api/v1/admin/documents",
            files={"file": ("evil.exe", b"x", "application/octet-stream")},
        )
        assert res.status_code == 400


def test_public_upload_too_large_is_413(tmp_path, sqlite_url, monkeypatch):
    import ragkb.services.documents as documents_module

    monkeypatch.setattr(documents_module, "MAX_UPLOAD_BYTES", 10)
    cfg = _public_client_cfg(tmp_path, sqlite_url)
    with TestClient(make_app(cfg)) as client:
        res = client.post(
            "/api/v1/admin/documents",
            files={"file": ("big.md", b"a" * 20, "text/markdown")},
        )
        assert res.status_code == 413


def test_public_delete(tmp_path, sqlite_url):
    cfg = _public_client_cfg(tmp_path, sqlite_url)
    with TestClient(make_app(cfg)) as client:
        client.post(
            "/api/v1/admin/documents",
            files={"file": ("new.md", "# N\n\nТекст.\n".encode(), "text/markdown")},
        )
        res = client.delete("/api/v1/admin/documents/new.md")
        assert res.status_code == 204
        assert client.delete("/api/v1/admin/documents/new.md").status_code == 404


def test_public_delete_of_unregistered_file_is_404(tmp_path, sqlite_url):
    """Файл мимо реестра удалять нечего: в корпусе его нет."""
    cfg = _public_client_cfg(tmp_path, sqlite_url)
    with TestClient(make_app(cfg)) as client:
        assert client.delete("/api/v1/admin/documents/policy.md").status_code == 404


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
