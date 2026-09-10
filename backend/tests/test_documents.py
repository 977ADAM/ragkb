import asyncio
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config as AlembicConfig
from fastapi.testclient import TestClient
from helpers import BACKEND_ROOT, make_app

from ragkb.core.config import Settings
from ragkb.core.database import make_engine, make_session_factory
from ragkb.core.errors import EngineUnavailable, InvalidRequest, NotFound, PayloadTooLarge
from ragkb.core.index import ConfigIndex
from ragkb.core.pipeline import RAGPipeline, build_index, update_documents
from ragkb.db.repos.auth import PostgresAccounts
from ragkb.domain.entities import ORIGIN_EXTERNAL, ORIGIN_UI, CorpusDocument
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


class MemoryRegistry:
    """Реестр документов в памяти — замена Postgres в тестах сервиса."""

    def __init__(self) -> None:
        self.rows: dict[str, CorpusDocument] = {}

    async def names(self) -> set[str]:
        return set(self.rows)

    async def list_all(self) -> list[CorpusDocument]:
        return list(self.rows.values())

    async def record(
        self,
        name: str,
        *,
        origin: str = ORIGIN_UI,
        uploaded_by: str = "",
        size: int = 0,
        sha256: str = "",
    ) -> None:
        self.rows[name] = CorpusDocument(
            name=name,
            origin=origin,
            uploaded_by=uploaded_by,
            uploaded_at="2026-09-10T00:00:00+00:00",
            size=size,
            sha256=sha256,
        )

    async def forget(self, name: str) -> bool:
        return self.rows.pop(name, None) is not None


def make_service(cfg: Settings, registry=None, invalidate=None) -> DocumentsService:
    def get_engine():
        try:
            return RAGPipeline(cfg)
        except (FileNotFoundError, ValueError) as exc:
            raise EngineUnavailable(str(exc)) from exc

    return DocumentsService(
        cfg,
        ConfigIndex(cfg, get_engine),
        invalidate or (lambda: None),
        registry,
    )


def _chroma_available() -> bool:
    try:
        import chromadb  # noqa: F401
        return True
    except ImportError:
        return False


async def test_list_after_build(tmp_path):
    cfg = make_cfg(tmp_path)
    build_index(cfg)
    svc = make_service(cfg)
    body = await svc.list_documents()
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


async def test_list_new_file_is_new(tmp_path):
    cfg = make_cfg(tmp_path)
    build_index(cfg)
    (Path(cfg.docs_dir) / "fresh.md").write_text("# Новый\n\nТекст.\n", encoding="utf-8")
    body = await make_service(cfg).list_documents()
    by_name = {r["name"]: r for r in body["corpus"]}
    assert by_name["fresh.md"]["state"] == "new"
    assert by_name["fresh.md"]["indexed"] is False


async def test_list_stale_when_mtime_newer(tmp_path):
    cfg = make_cfg(tmp_path)
    build_index(cfg)
    target = Path(cfg.docs_dir) / "policy.md"
    future = datetime.now(timezone.utc).timestamp() + 3600
    os.utime(target, (future, future))
    body = await make_service(cfg).list_documents()
    row = next(r for r in body["corpus"] if r["name"] == "policy.md")
    assert row["state"] == "stale"


async def test_list_orphan_when_file_removed(tmp_path):
    cfg = make_cfg(tmp_path)
    build_index(cfg)
    (Path(cfg.docs_dir) / "policy.md").unlink()
    body = await make_service(cfg).list_documents()
    assert len(body["orphans"]) == 1
    assert body["orphans"][0]["source"].endswith("policy.md")


async def test_list_no_index(tmp_path):
    cfg = make_cfg(tmp_path)  # индекс не собран
    body = await make_service(cfg).list_documents()
    assert body["index"] == "no_index"
    assert body["built_at"] is None
    assert body["orphans"] == [] and body["skipped"] == []
    assert body["corpus"][0]["state"] is None


def _manifest(cfg: Settings) -> dict:
    return json.loads(
        (Path(cfg.index_dir) / "manifest.json").read_text(encoding="utf-8")
    )


def test_manifest_keeps_file_facts(tmp_path):
    """В манифесте остаются факты о файле: по ним судим о состоянии."""
    cfg = make_cfg(tmp_path)
    build_index(cfg)
    target = Path(cfg.docs_dir) / "policy.md"
    entry = _manifest(cfg)["documents"][0]
    assert entry["size"] == target.stat().st_size
    assert len(entry["sha256"]) == 64
    assert datetime.fromisoformat(entry["mtime"])


async def test_list_detects_replaced_file_with_older_mtime(tmp_path):
    """Файл заменили копией с прежней датой: дата молчит, содержимое говорит."""
    cfg = make_cfg(tmp_path)
    build_index(cfg)
    target = Path(cfg.docs_dir) / "policy.md"
    target.write_text(
        "# Политика\n\n## Отпуск\n\nЕжегодный отпуск составляет 14 календарных дней.\n",
        encoding="utf-8",
    )
    past = datetime.now(timezone.utc).timestamp() - 3600
    os.utime(target, (past, past))
    row = next(
        r for r in (await make_service(cfg).list_documents())["corpus"] if r["name"] == "policy.md"
    )
    assert row["state"] == "stale"


async def test_list_keeps_indexed_for_untouched_file(tmp_path):
    """Переиндексация соседнего файла не делает изменёнными все остальные."""
    cfg = make_cfg(tmp_path)
    build_index(cfg)
    (Path(cfg.docs_dir) / "fresh.md").write_text("# Новый\n\nТекст.\n", encoding="utf-8")
    build_index(cfg)
    body = await make_service(cfg).list_documents()
    by_name = {r["name"]: r for r in body["corpus"]}
    assert by_name["policy.md"]["state"] == "indexed"
    assert by_name["fresh.md"]["state"] == "indexed"


async def test_list_without_facts_falls_back_to_built_at(tmp_path):
    """Индекс, собранный прежней версией, читается по старому признаку."""
    cfg = make_cfg(tmp_path)
    build_index(cfg)
    manifest_path = Path(cfg.index_dir) / "manifest.json"
    manifest = _manifest(cfg)
    for entry in manifest["documents"]:
        for key in ("mtime", "size", "sha256"):
            entry.pop(key, None)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    row = next(
        r for r in (await make_service(cfg).list_documents())["corpus"] if r["name"] == "policy.md"
    )
    assert row["state"] == "indexed"


def test_incremental_update_keeps_facts(tmp_path):
    """Инкрементальное обновление не должно терять факты о документах."""
    if not _chroma_available():
        pytest.skip("chromadb не установлена")
    cfg = make_cfg(tmp_path)
    cfg.store.backend = "chroma"
    build_index(cfg)
    fresh = Path(cfg.docs_dir) / "fresh.md"
    fresh.write_text("# Новый\n\nПравило про отпуск: 28 дней.\n", encoding="utf-8")
    update_documents(cfg, [fresh])
    by_source = {d["source"]: d for d in _manifest(cfg)["documents"]}
    assert len(by_source) == 2
    assert all(len(d.get("sha256", "")) == 64 for d in by_source.values())
    assert all(d.get("size") for d in by_source.values())


async def test_upload_saves_file_and_reindexes(tmp_path):
    cfg = make_cfg(tmp_path)
    build_index(cfg)
    svc = make_service(cfg)
    report = await svc.upload("new.md", "# Новый\n\nПравило про отпуск: 28 дней.\n".encode())
    assert report["files"] >= 1
    assert (Path(cfg.docs_dir) / "new.md").exists()
    body = await svc.list_documents()
    assert len(body["corpus"]) == 2
    assert all(r["indexed"] for r in body["corpus"])


async def test_upload_rejects_bad_extension(tmp_path):
    cfg = make_cfg(tmp_path)
    svc = make_service(cfg)
    with pytest.raises(InvalidRequest):
        await svc.upload("evil.exe", b"x" * 10)


async def test_upload_rejects_hidden_name(tmp_path):
    cfg = make_cfg(tmp_path)
    svc = make_service(cfg)
    with pytest.raises(InvalidRequest):
        await svc.upload(".env", b"SECRET=1\n")


async def test_upload_rolls_back_when_corpus_empty(tmp_path, monkeypatch):
    cfg = make_cfg(tmp_path)
    (Path(cfg.docs_dir) / "policy.md").unlink()
    svc = make_service(cfg)
    # файл с расширением, но без текста — build_index упадёт целиком
    with pytest.raises(InvalidRequest):
        await svc.upload("scan.pdf", b"%PDF-1.4 no text layer")
    assert not (Path(cfg.docs_dir) / "scan.pdf").exists()


async def test_upload_size_limit(tmp_path):
    cfg = make_cfg(tmp_path)
    svc = make_service(cfg)
    with pytest.raises(PayloadTooLarge):
        await svc.upload("big.md", b"a" * (MAX_UPLOAD_BYTES + 1))


# --------------------------------------------------- корпус только через UI


async def test_external_file_is_listed_but_not_indexed(tmp_path):
    """Файл мимо интерфейса виден, но в базу знаний не попадает."""
    cfg = make_cfg(tmp_path)
    registry = MemoryRegistry()
    svc = make_service(cfg, registry)
    await svc.upload("ours.md", "# Наш\n\nПравило про отпуск: 28 дней.\n".encode(), "ada")
    # policy.md лежит в каталоге с самого начала и в реестр не занесён
    body = await svc.list_documents()
    rows = {r["name"]: r for r in body["corpus"]}
    assert rows["policy.md"]["registered"] is False
    assert rows["policy.md"]["state"] == "external"
    assert rows["ours.md"]["state"] == "indexed"
    assert body["registry"] == "on"
    assert body["summary"]["external_files"] == 1
    sources = {d["source"] for d in _manifest(cfg)["documents"]}
    assert any(s.endswith("ours.md") for s in sources)
    assert not any(s.endswith("policy.md") for s in sources)


async def test_external_document_is_not_searchable(tmp_path):
    """Главное требование: непринятый документ не участвует в ответах."""
    cfg = make_cfg(tmp_path)
    (Path(cfg.docs_dir) / "secret.md").write_text(
        "# Секрет\n\nКод доступа к хранилищу: КАРАНДАШ-77.\n", encoding="utf-8"
    )
    svc = make_service(cfg, MemoryRegistry())
    await svc.upload("ours.md", "# Наш\n\nПравило про отпуск: 28 дней.\n".encode(), "ada")
    hits = RAGPipeline(cfg).search("код доступа к хранилищу", top_k=3)
    assert all("КАРАНДАШ" not in hit.chunk.text for hit in hits)


async def test_accept_takes_external_file_into_corpus(tmp_path):
    cfg = make_cfg(tmp_path)
    registry = MemoryRegistry()
    svc = make_service(cfg, registry)
    report = await svc.accept(["policy.md"], "ada")
    assert report["accepted"] == ["policy.md"]
    assert registry.rows["policy.md"].origin == ORIGIN_EXTERNAL
    body = await svc.list_documents()
    row = body["corpus"][0]
    assert row["state"] == "indexed"
    assert row["origin"] == ORIGIN_EXTERNAL
    assert body["summary"]["external_files"] == 0


async def test_accept_nested_file_uses_relative_name(tmp_path):
    """В подкаталогах корпуса документ адресуется относительным путём."""
    cfg = make_cfg(tmp_path)
    nested = Path(cfg.docs_dir) / "hr"
    nested.mkdir()
    (nested / "otpusk.md").write_text("# Отпуск\n\n28 календарных дней.\n", encoding="utf-8")
    registry = MemoryRegistry()
    svc = make_service(cfg, registry)
    await svc.accept(["hr/otpusk.md"], "ada")
    assert "hr/otpusk.md" in registry.rows
    await svc.delete("hr/otpusk.md")
    assert not (nested / "otpusk.md").exists()
    assert registry.rows == {}


async def test_accept_missing_file_is_404(tmp_path):
    cfg = make_cfg(tmp_path)
    with pytest.raises(NotFound):
        await make_service(cfg, MemoryRegistry()).accept(["nope.md"], "ada")


async def test_accept_requires_registry(tmp_path):
    cfg = make_cfg(tmp_path)
    with pytest.raises(InvalidRequest):
        await make_service(cfg).accept(["policy.md"], "ada")


async def test_delete_forgets_registry_row(tmp_path):
    cfg = make_cfg(tmp_path)
    registry = MemoryRegistry()
    svc = make_service(cfg, registry)
    await svc.upload("new.md", "# Новый\n\nТекст про отпуск.\n".encode(), "ada")
    assert "new.md" in registry.rows
    await svc.delete("new.md")
    assert registry.rows == {}


async def test_delete_rejects_path_outside_corpus(tmp_path):
    cfg = make_cfg(tmp_path)
    with pytest.raises(InvalidRequest):
        await make_service(cfg).delete("../outside.md")


async def test_upload_without_index_defers_rebuild(tmp_path):
    """Пачка грузится без индексации на каждый файл — сборка одна, в конце."""
    cfg = make_cfg(tmp_path)
    registry = MemoryRegistry()
    svc = make_service(cfg, registry)
    # Индекс уже собран по принятому документу, иначе состояние было бы «—».
    await svc.accept(["policy.md"], "ada")
    result = await svc.upload(
        "new.md", "# Новый\n\nТекст про отпуск.\n".encode(), "ada", index=False
    )
    assert result["indexed"] is False
    body = await svc.list_documents()
    row = next(r for r in body["corpus"] if r["name"] == "new.md")
    assert row["registered"] is True and row["state"] == "new"
    assert "new.md" in registry.rows


async def test_without_registry_indexes_whole_catalog(tmp_path):
    """Без реестра (нет БД) поведение прежнее: индексируется весь каталог."""
    cfg = make_cfg(tmp_path)
    svc = make_service(cfg)
    await svc.upload("new.md", "# Новый\n\nТекст про отпуск.\n".encode(), "ada")
    body = await svc.list_documents()
    assert body["registry"] == "off"
    assert all(r["registered"] for r in body["corpus"])
    assert all(r["indexed"] for r in body["corpus"])


async def test_upload_invalidates_engine(tmp_path):
    """После загрузки движок сбрасывается — иначе поиск шёл бы по старому."""
    cfg = make_cfg(tmp_path)
    dropped: list[bool] = []
    svc = make_service(cfg, MemoryRegistry(), invalidate=lambda: dropped.append(True))
    await svc.upload("new.md", "# Новый\n\nТекст про отпуск.\n".encode(), "ada")
    assert dropped, "кеш движка не сброшен: свежий индекс не увидит загруженный документ"


async def test_accept_invalidates_engine(tmp_path):
    cfg = make_cfg(tmp_path)
    dropped: list[bool] = []
    svc = make_service(cfg, MemoryRegistry(), invalidate=lambda: dropped.append(True))
    await svc.accept(["policy.md"], "ada")
    assert dropped


async def test_delete_removes_file_and_index_entry(tmp_path):
    cfg = make_cfg(tmp_path)
    build_index(cfg)
    (Path(cfg.docs_dir) / "policy.md").write_text(
        "# A\n\n## B\n\n" + "x" * 2000 + "\n", encoding="utf-8"
    )
    # второй документ, чтобы после удаления корпус не опустел
    (Path(cfg.docs_dir) / "keep.md").write_text("# Keep\n\nТекст для чанка.\n", encoding="utf-8")
    build_index(cfg)
    svc = make_service(cfg)
    await svc.delete("policy.md")
    assert not (Path(cfg.docs_dir) / "policy.md").exists()
    body = await svc.list_documents()
    names = {r["name"] for r in body["corpus"]}
    assert "policy.md" not in names and "keep.md" in names


async def test_delete_missing_file_is_404(tmp_path):
    cfg = make_cfg(tmp_path)
    build_index(cfg)
    with pytest.raises(NotFound):
        await make_service(cfg).delete("nope.md")


async def test_delete_last_doc_clears_index(tmp_path):
    cfg = make_cfg(tmp_path)
    build_index(cfg)
    await make_service(cfg).delete("policy.md")
    body = await make_service(cfg).list_documents()
    assert body["index"] == "no_index"


async def test_delete_on_chroma_is_point_removal(tmp_path):
    pytest.importorskip("chromadb")
    cfg = make_cfg(tmp_path)
    cfg.store.backend = "chroma"
    build_index(cfg)
    (Path(cfg.docs_dir) / "keep.md").write_text("# Keep\n\nТекст.\n", encoding="utf-8")
    build_index(cfg)
    await make_service(cfg).delete("keep.md")
    body = await make_service(cfg).list_documents()
    assert all(r["name"] != "keep.md" for r in body["corpus"])


async def test_delete_last_doc_clears_chroma_index(tmp_path):
    pytest.importorskip("chromadb")
    cfg = make_cfg(tmp_path)
    cfg.store.backend = "chroma"
    build_index(cfg)
    await make_service(cfg).delete("policy.md")
    body = await make_service(cfg).list_documents()
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
    with TestClient(make_app(cfg)) as client:
        _signin(client, "bob")
        assert client.get("/api/v1/admin/documents").status_code == 403
        assert client.post(
            "/api/v1/admin/documents", files={"file": ("x.md", b"# X", "text/markdown")}
        ).status_code == 403
        assert client.delete("/api/v1/admin/documents/x.md").status_code == 403


def test_admin_gets_document_list(tmp_path, sqlite_url):
    cfg = _session_client_cfg(tmp_path, sqlite_url)
    with TestClient(make_app(cfg)) as client:
        _signin(client, "ada")
        body = client.get("/api/v1/admin/documents").json()
        assert body["index"] == "no_index"
        assert body["corpus"][0]["name"] == "policy.md"


def test_admin_upload_and_list(tmp_path, sqlite_url):
    cfg = _session_client_cfg(tmp_path, sqlite_url)
    with TestClient(make_app(cfg)) as client:
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


def test_admin_accept_flow(tmp_path, sqlite_url):
    """Файл из каталога сначала вне корпуса, после принятия — в индексе."""
    cfg = _session_client_cfg(tmp_path, sqlite_url)
    with TestClient(make_app(cfg)) as client:
        _signin(client, "ada")
        before = client.get("/api/v1/admin/documents").json()
        assert before["registry"] == "on"
        row = before["corpus"][0]
        assert row["state"] == "external" and row["registered"] is False

        accepted = client.post(
            "/api/v1/admin/documents/accept", json={"names": ["policy.md"]}
        )
        assert accepted.status_code == 200
        assert accepted.json()["accepted"] == ["policy.md"]

        after = client.get("/api/v1/admin/documents").json()
        row = after["corpus"][0]
        assert row["state"] == "indexed"
        assert row["origin"] == "external"
        assert row["uploaded_by"] == "ada"
        assert after["summary"]["external_files"] == 0

        names = client.get("/api/v1/admin/documents").json()["corpus"]
        assert names[0]["name"] == "policy.md"


def test_admin_rebuild_without_accepted_documents_is_400(tmp_path, sqlite_url):
    """Пока в корпус ничего не принято, собирать индекс не из чего."""
    cfg = _session_client_cfg(tmp_path, sqlite_url)
    with TestClient(make_app(cfg)) as client:
        _signin(client, "ada")
        res = client.post("/api/v1/index/rebuild")
        assert res.status_code == 400
        assert "примите" in res.json()["detail"].lower()


def test_admin_batch_upload_uses_single_rebuild(tmp_path, sqlite_url):
    """Очередь загрузки не индексирует каждый файл по отдельности."""
    cfg = _session_client_cfg(tmp_path, sqlite_url)
    with TestClient(make_app(cfg)) as client:
        _signin(client, "ada")
        for name in ("one.md", "two.md"):
            res = client.post(
                "/api/v1/admin/documents",
                params={"index": "false"},
                files={"file": (name, f"# {name}\n\nТекст.\n".encode(), "text/markdown")},
            )
            assert res.status_code == 200
            assert res.json()["indexed"] is False

        body = client.get("/api/v1/admin/documents").json()
        assert body["index"] == "no_index"

        rebuilt = client.post("/api/v1/index/rebuild")
        assert rebuilt.status_code == 200
        assert rebuilt.json()["files"] == 2

        after = client.get("/api/v1/admin/documents").json()
        assert {r["name"]: r["state"] for r in after["corpus"]} == {
            "one.md": "indexed",
            "two.md": "indexed",
            "policy.md": "external",
        }
        assert after["summary"]["external_files"] == 1


def test_admin_accept_unknown_file_is_404(tmp_path, sqlite_url):
    cfg = _session_client_cfg(tmp_path, sqlite_url)
    with TestClient(make_app(cfg)) as client:
        _signin(client, "ada")
        res = client.post("/api/v1/admin/documents/accept", json={"names": ["nope.md"]})
        assert res.status_code == 404


def test_admin_upload_bad_extension_is_400(tmp_path, sqlite_url):
    cfg = _session_client_cfg(tmp_path, sqlite_url)
    with TestClient(make_app(cfg)) as client:
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
    with TestClient(make_app(cfg)) as client:
        _signin(client, "ada")
        res = client.post(
            "/api/v1/admin/documents",
            files={"file": ("big.md", b"a" * 20, "text/markdown")},
        )
        assert res.status_code == 413


def test_admin_delete(tmp_path, sqlite_url):
    cfg = _session_client_cfg(tmp_path, sqlite_url)
    with TestClient(make_app(cfg)) as client:
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
