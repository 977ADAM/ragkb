"""Выдача оригинала документа: проверки реестра, пути и HTTP-контракт.

`download_allowed` управляет только выдачей файла: поиск, ответы и цитаты по
закрытому документу работают по-прежнему. Путь берётся исключительно из записи
реестра, файл открывается без прохода по компонентам-симлинкам и отдаётся из
уже проверенного дескриптора, а прежнее значение разрешения читается в той же
транзакции, что и запись нового.

Корпус и база здесь временные: реальные документы и рабочая БД не участвуют.
"""
from __future__ import annotations

import asyncio
import logging
import sqlite3
import uuid
from dataclasses import replace
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config as AlembicConfig
from fastapi.testclient import TestClient
from helpers import BACKEND_ROOT, make_app

from ragkb.core.config import Settings

POLICY = "# Политика\n\n## Отпуск\n\nЕжегодный отпуск — 28 календарных дней.\n"
# Небольшой, но настоящий PDF: выдача проверяет байты, а не разбор текста.
PDF = b"%PDF-1.4\n1 0 obj<</Type/Catalog>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF\n"
CYRILLIC_NAME = "Требования AdSmart #1.pdf"


# --------------------------------------------------------------- окружение


def _database_path(url: str) -> Path:
    raw = url.removeprefix("sqlite+aiosqlite:///").split("?", 1)[0]
    return Path(raw)


def _migrate(url: str, monkeypatch: pytest.MonkeyPatch) -> None:
    config = AlembicConfig(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "migrations"))
    monkeypatch.setenv("RAGKB_DATABASE_URL", url)
    command.upgrade(config, "head")


@pytest.fixture
def sqlite_url(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    url = f"sqlite+aiosqlite:///{tmp_path / 'ragkb.sqlite3'}"
    _migrate(url, monkeypatch)
    return url


def _cfg(tmp_path: Path, url: str = "") -> Settings:
    docs = tmp_path / "docs"
    docs.mkdir(exist_ok=True)
    cfg = Settings(
        docs_dir=str(docs),
        index_dir=str(tmp_path / "index"),
        organization=Settings.OrganizationConfig(name="Acme", id="acme"),
    )
    cfg.store.backend = "memory"
    cfg.database_url = url
    cfg.logging.dir = str(tmp_path / "logs")
    return cfg


def _upload(client: TestClient, name: str, data: bytes = PDF, **params) -> dict:
    query = {"index": "false", **params}
    response = client.post(
        "/api/v1/admin/documents",
        params=query,
        files={"file": (name, data, "application/pdf")},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _row(client: TestClient, name: str) -> dict:
    corpus = client.get("/api/v1/admin/documents").json()["corpus"]
    return next(row for row in corpus if row["name"] == name)


def _urls(row: dict) -> tuple[str, str]:
    download = f"/api/v1/documents/{row['document_id']}/download"
    return download, download.removesuffix("/download") + "/download-permission"


def _allow(client: TestClient, row: dict) -> None:
    _, permission = _urls(row)
    response = client.patch(permission, json={"download_allowed": True})
    assert response.status_code == 200, response.text


def _seed_registry_row(url: str, name: str, *, allowed: bool = True) -> str:
    """Заводит запись реестра сырым SQL: такое имя загрузка не пропустит."""
    document_id = str(uuid.uuid4())
    with sqlite3.connect(_database_path(url)) as connection:
        connection.execute(
            "INSERT INTO corpus_documents (name, document_id, uploaded_at, download_allowed)"
            " VALUES (?, ?, '2026-09-22T00:00:00+00:00', ?)",
            (name, document_id, 1 if allowed else 0),
        )
    return document_id


# ------------------------------------------------------- основной контракт


def test_uploaded_document_is_closed_until_permission_is_given(tmp_path, sqlite_url):
    cfg = _cfg(tmp_path, sqlite_url)
    with TestClient(make_app(cfg)) as client:
        _upload(client, "spec.pdf")
        row = _row(client, "spec.pdf")
        download, permission = _urls(row)
        assert row["download_allowed"] is False
        assert uuid.UUID(row["document_id"])

        refused = client.get(download)
        assert refused.status_code == 404
        assert refused.headers["cache-control"] == "no-store"
        assert client.head(download).status_code == 404

        allowed = client.patch(permission, json={"download_allowed": True})
        assert allowed.status_code == 200
        assert allowed.json() == {
            "document_id": row["document_id"],
            "download_allowed": True,
        }

        served = client.get(download)
        assert served.status_code == 200
        assert served.content == PDF
        assert served.headers["content-type"] == "application/pdf"
        assert served.headers["content-length"] == str(len(PDF))
        assert served.headers["cache-control"] == "no-store"
        assert served.headers["content-disposition"].startswith("attachment")
        assert "accept-ranges" not in served.headers

        client.patch(permission, json={"download_allowed": False})
        assert client.get(download).status_code == 404


def test_head_returns_headers_without_body(tmp_path, sqlite_url):
    cfg = _cfg(tmp_path, sqlite_url)
    with TestClient(make_app(cfg)) as client:
        _upload(client, "spec.pdf")
        row = _row(client, "spec.pdf")
        download, _ = _urls(row)
        _allow(client, row)

        response = client.head(download)

        assert response.status_code == 200
        assert response.content == b""
        assert response.headers["content-length"] == str(len(PDF))
        assert response.headers["cache-control"] == "no-store"
        assert "attachment" in response.headers["content-disposition"]


def test_range_request_is_answered_with_full_body(tmp_path, sqlite_url):
    """Частичных ответов в первой версии нет: Range получает полный 200."""
    cfg = _cfg(tmp_path, sqlite_url)
    with TestClient(make_app(cfg)) as client:
        _upload(client, "spec.pdf")
        row = _row(client, "spec.pdf")
        download, _ = _urls(row)
        _allow(client, row)

        response = client.get(download, headers={"range": "bytes=0-3"})

        assert response.status_code == 200
        assert response.content == PDF
        assert "content-range" not in response.headers
        assert "accept-ranges" not in response.headers


def test_permission_change_needs_no_reindex_and_keeps_search(tmp_path, sqlite_url):
    cfg = _cfg(tmp_path, sqlite_url)
    with TestClient(make_app(cfg)) as client:
        _upload(client, "policy.md", POLICY.encode(), index="true")
        row = _row(client, "policy.md")
        download, permission = _urls(row)
        built_at = client.get("/api/v1/admin/documents").json()["built_at"]
        assert client.get(download).status_code == 404

        assert client.patch(permission, json={"download_allowed": True}).status_code == 200

        after = client.get("/api/v1/admin/documents").json()
        assert after["built_at"] == built_at, "разрешение не требует переиндексации"
        assert _row(client, "policy.md")["download_allowed"] is True
        assert client.get(download).content == POLICY.encode()
        # Закрытый для скачивания документ остаётся в поиске и цитатах.
        found = client.post("/api/v1/search", json={"query": "отпуск", "top_k": 5})
        assert found.status_code == 200
        assert found.json()["results"]


def test_replacement_keeps_id_and_resets_permission_without_explicit_flag(
    tmp_path, sqlite_url
):
    cfg = _cfg(tmp_path, sqlite_url)
    with TestClient(make_app(cfg)) as client:
        _upload(client, "spec.pdf", PDF, download_allowed="true")
        row = _row(client, "spec.pdf")
        download, _ = _urls(row)
        assert row["download_allowed"] is True
        assert client.get(download).status_code == 200

        replacement = PDF + "заменено".encode()
        _upload(client, "spec.pdf", replacement)

        replaced = _row(client, "spec.pdf")
        assert replaced["document_id"] == row["document_id"]
        assert replaced["download_allowed"] is False
        assert client.get(download).status_code == 404
        # Разрешение не наследуется молча: его выдают заново явным параметром.
        _allow(client, replaced)
        assert client.get(download).content == replacement


# ------------------------------------------------------- отказы и пути


def test_unknown_document_and_foreign_id_are_404(tmp_path, sqlite_url):
    cfg = _cfg(tmp_path, sqlite_url)
    with TestClient(make_app(cfg)) as client:
        _upload(client, "spec.pdf")
        row = _row(client, "spec.pdf")

        assert client.get(f"/api/v1/documents/{uuid.uuid4()}/download").status_code == 404
        assert client.get("/api/v1/documents/не-uuid/download").status_code == 404
        unknown = client.patch(
            f"/api/v1/documents/{uuid.uuid4()}/download-permission",
            json={"download_allowed": True},
        )
        assert unknown.status_code == 404
        assert row["download_allowed"] is False


def test_file_outside_registry_has_no_download_id(tmp_path, sqlite_url):
    """Файл, положенный в каталог мимо интерфейса, нечем запросить на скачивание."""
    cfg = _cfg(tmp_path, sqlite_url)
    (Path(cfg.docs_dir) / "secret.pdf").write_bytes("%PDF секрет\n".encode())
    with TestClient(make_app(cfg)) as client:
        _upload(client, "spec.pdf")
        listed = client.get("/api/v1/admin/documents").json()["corpus"]
        assert [row["name"] for row in listed] == ["spec.pdf"]

        for document_id in [row["document_id"] for row in listed] + [str(uuid.uuid4())]:
            response = client.get(f"/api/v1/documents/{document_id}/download")
            assert response.status_code == 404
            assert "секрет".encode() not in response.content


def test_traversal_out_of_docs_dir_is_refused(tmp_path, sqlite_url):
    cfg = _cfg(tmp_path, sqlite_url)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.pdf").write_bytes("%PDF снаружи\n".encode())
    with TestClient(make_app(cfg)) as client:
        for name in ("../outside/secret.pdf", "/etc/passwd", "sub/../../outside/secret.pdf"):
            document_id = _seed_registry_row(sqlite_url, name)
            response = client.get(f"/api/v1/documents/{document_id}/download")
            assert response.status_code == 404, name
            assert "снаружи".encode() not in response.content


def test_symlink_components_are_refused(tmp_path, sqlite_url):
    """Симлинк не обходит проверку: ни конечный, ни промежуточный."""
    cfg = _cfg(tmp_path, sqlite_url)
    docs = Path(cfg.docs_dir)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.pdf").write_bytes("%PDF снаружи\n".encode())
    (docs / "real.pdf").write_bytes(PDF)
    (docs / "inside.pdf").symlink_to(docs / "real.pdf")
    (docs / "escape.pdf").symlink_to(outside / "secret.pdf")
    (docs / "sub").symlink_to(outside)
    with TestClient(make_app(cfg)) as client:
        for name in ("inside.pdf", "escape.pdf", "sub/secret.pdf"):
            document_id = _seed_registry_row(sqlite_url, name)
            response = client.get(f"/api/v1/documents/{document_id}/download")
            assert response.status_code == 404, name
            assert response.content != "%PDF снаружи\n".encode()
            assert response.content != PDF


def test_missing_file_is_404(tmp_path, sqlite_url):
    cfg = _cfg(tmp_path, sqlite_url)
    with TestClient(make_app(cfg)) as client:
        _upload(client, "spec.pdf")
        row = _row(client, "spec.pdf")
        download, _ = _urls(row)
        _allow(client, row)
        (Path(cfg.docs_dir) / "spec.pdf").unlink()

        assert client.get(download).status_code == 404
        assert client.head(download).status_code == 404


def test_without_registry_download_is_404_and_change_is_400(tmp_path):
    cfg = _cfg(tmp_path)
    with TestClient(make_app(cfg)) as client:
        document_id = str(uuid.uuid4())
        refused = client.get(f"/api/v1/documents/{document_id}/download")
        assert refused.status_code == 404
        assert refused.headers["cache-control"] == "no-store"

        changed = client.patch(
            f"/api/v1/documents/{document_id}/download-permission",
            json={"download_allowed": True},
        )
        assert changed.status_code == 400
        assert "RAGKB_DATABASE_URL" in changed.json()["detail"]


def test_permission_payload_is_strict(tmp_path, sqlite_url):
    cfg = _cfg(tmp_path, sqlite_url)
    with TestClient(make_app(cfg)) as client:
        _upload(client, "spec.pdf")
        row = _row(client, "spec.pdf")
        _, permission = _urls(row)

        assert client.patch(permission, json={"download_allowed": "да"}).status_code == 422
        assert (
            client.patch(permission, json={"download_allowed": True, "extra": 1}).status_code
            == 422
        )


# ------------------------------------------------------- имена и типы


def test_cyrillic_name_is_served_with_rfc5987_disposition(tmp_path, sqlite_url):
    cfg = _cfg(tmp_path, sqlite_url)
    with TestClient(make_app(cfg)) as client:
        _upload(client, CYRILLIC_NAME)
        row = _row(client, CYRILLIC_NAME)
        download, _ = _urls(row)
        _allow(client, row)

        response = client.get(download)

        assert response.status_code == 200
        assert response.content == PDF
        disposition = response.headers["content-disposition"]
        assert "filename*=UTF-8''" in disposition
        assert "%D0%A2%D1%80%D0%B5%D0%B1%D0%BE%D0%B2%D0%B0%D0%BD%D0%B8%D1%8F" in disposition
        assert "#" not in disposition.split("filename*=UTF-8''", 1)[1]


def test_unknown_extension_is_served_as_binary(tmp_path, sqlite_url):
    cfg = _cfg(tmp_path, sqlite_url)
    (Path(cfg.docs_dir) / "data.bin").write_bytes(b"\x00\x01\x02")
    with TestClient(make_app(cfg)) as client:
        document_id = _seed_registry_row(sqlite_url, "data.bin")

        response = client.get(f"/api/v1/documents/{document_id}/download")

        assert response.status_code == 200
        assert response.headers["content-type"] == "application/octet-stream"
        assert response.content == b"\x00\x01\x02"


# ------------------------------------------------------- блокировка БД


def test_busy_database_is_reported_as_conflict(tmp_path, monkeypatch):
    """Занятость базы — понятный отказ с повтором, а не 500 и не тишина."""
    database = tmp_path / "ragkb.sqlite3"
    url = f"sqlite+aiosqlite:///{database}?timeout=0.1"
    _migrate(url, monkeypatch)
    cfg = _cfg(tmp_path, url)
    with TestClient(make_app(cfg)) as client:
        _upload(client, "spec.pdf")
        row = _row(client, "spec.pdf")
        _, permission = _urls(row)

        blocker = sqlite3.connect(database)
        try:
            blocker.execute("BEGIN IMMEDIATE")
            response = client.patch(permission, json={"download_allowed": True})
        finally:
            blocker.rollback()
            blocker.close()

        assert response.status_code == 409
        assert "повтор" in response.json()["detail"].lower()
        # После снятия блокировки изменение проходит без правок состояния.
        assert client.patch(permission, json={"download_allowed": True}).status_code == 200


def test_other_database_errors_are_not_masked(tmp_path, sqlite_url):
    """Поломка схемы остаётся ошибкой сервера: её нельзя выдать за занятость."""
    cfg = _cfg(tmp_path, sqlite_url)
    with sqlite3.connect(_database_path(sqlite_url)) as connection:
        connection.execute("DROP TABLE corpus_documents")
    with TestClient(make_app(cfg), raise_server_exceptions=False) as client:
        response = client.patch(
            f"/api/v1/documents/{uuid.uuid4()}/download-permission",
            json={"download_allowed": True},
        )
        assert response.status_code == 500
        assert "повтор" not in response.text.lower()


# ------------------------------------------------------------- журнал


def _audit_lines(cfg: Settings) -> list[str]:
    for handler in logging.getLogger().handlers:
        handler.flush()
    path = Path(cfg.logging.dir) / "app.log"
    if not path.exists():
        return []
    return [
        line
        for line in path.read_text(encoding="utf-8").splitlines()
        if "download_permission" in line
    ]


def test_permission_changes_are_written_to_audit_log(tmp_path, sqlite_url):
    cfg = _cfg(tmp_path, sqlite_url)
    with TestClient(make_app(cfg)) as client:
        _upload(client, "spec.pdf", PDF, download_allowed="true")
        row = _row(client, "spec.pdf")
        _, permission = _urls(row)
        client.patch(
            permission,
            json={"download_allowed": False},
            headers={"x-request-id": "req-1"},
        )

    lines = _audit_lines(cfg)
    assert any(
        "result=ok" in line and "old=false" in line and "new=true" in line for line in lines
    ), lines
    assert any(
        "request_id=req-1" in line and "old=true" in line and "new=false" in line
        for line in lines
    ), lines
    assert uuid.UUID(row["document_id"])  # идентификатор есть в записи журнала
    assert all(row["document_id"] in line for line in lines if "new=" in line)


def test_refused_change_is_not_logged_as_saved(tmp_path, sqlite_url):
    cfg = _cfg(tmp_path, sqlite_url)
    with TestClient(make_app(cfg)) as client:
        response = client.patch(
            f"/api/v1/documents/{uuid.uuid4()}/download-permission",
            json={"download_allowed": True},
        )
        assert response.status_code == 404

    assert _audit_lines(cfg) == []


# ------------------------------------------------------- дескрипторы


def test_opened_file_is_closed_after_response(tmp_path, sqlite_url, monkeypatch):
    """GET и HEAD закрывают дескриптор: файл не остаётся открытым после ответа."""
    from ragkb.services.downloads import DownloadsService

    cfg = _cfg(tmp_path, sqlite_url)
    opened: list = []
    original = DownloadsService.resolve

    async def tracking_resolve(self, document_id):
        descriptor = await original(self, document_id)
        opened.append(descriptor)
        return descriptor

    monkeypatch.setattr(DownloadsService, "resolve", tracking_resolve)
    with TestClient(make_app(cfg)) as client:
        _upload(client, "spec.pdf")
        row = _row(client, "spec.pdf")
        download, _ = _urls(row)
        _allow(client, row)

        assert client.get(download).status_code == 200
        assert client.head(download).status_code == 200
        # Отказ ничего не открывает вовсе.
        client.patch(_urls(row)[1], json={"download_allowed": False})
        assert client.get(download).status_code == 404

    assert len(opened) == 2, "отказ не должен доходить до открытия файла"
    assert all(descriptor.handle.closed for descriptor in opened)


async def test_file_is_streamed_in_chunks_and_closed_on_stream_error(
    tmp_path, sqlite_url, monkeypatch
):
    """Файл читается порциями, а обрыв отправки закрывает дескриптор."""
    from ragkb.api.routes.downloads import file_response
    from ragkb.core.database import make_engine, make_session_factory
    from ragkb.db.repos.corpus_documents import PostgresCorpusDocuments
    from ragkb.services.downloads import CHUNK_SIZE, DownloadsService

    cfg = _cfg(tmp_path, sqlite_url)
    payload = b"%PDF" + b"x" * (200 * 1024)
    (Path(cfg.docs_dir) / "big.pdf").write_bytes(payload)
    document_id = _seed_registry_row(sqlite_url, "big.pdf")
    engine = make_engine(sqlite_url)
    try:
        registry = PostgresCorpusDocuments(make_session_factory(engine))
        service = DownloadsService(Path(cfg.docs_dir), registry)
        descriptor = await service.resolve(document_id)
        reads: list[int] = []
        handle = descriptor.handle

        class Counting:
            closed = False

            def read(self, size: int = -1) -> bytes:
                reads.append(size)
                return handle.read(size)

            def close(self) -> None:
                self.closed = True
                handle.close()

        counter = Counting()
        streamed = replace(descriptor, handle=counter)
        response = file_response(streamed)
        sent: list[bytes] = []

        async def send(message) -> None:
            if message["type"] == "http.response.body" and message.get("body"):
                sent.append(message["body"])
                if len(sent) > 1:
                    raise RuntimeError("клиент отвалился")

        async def receive() -> dict:
            await asyncio.sleep(30)
            return {"type": "http.disconnect"}

        with pytest.raises(RuntimeError):
            await response(
                {"type": "http", "method": "GET", "headers": [(b"host", b"test")]}, receive, send
            )
    finally:
        await engine.dispose()

    assert len(reads) >= 2, "файл читается порциями, а не целиком в память"
    assert set(reads) == {CHUNK_SIZE}, reads
    assert payload.startswith(b"".join(sent)), "порции идут по порядку"
    assert sum(len(part) for part in sent) < len(payload), "отправка оборвалась на середине"
    assert counter.closed, "обрыв отправки должен закрыть дескриптор"
