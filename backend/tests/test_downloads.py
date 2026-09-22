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
import hashlib
import json
import logging
import os
import sqlite3
import subprocess
import sys
import textwrap
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


def _seed_registry_row(
    cfg: Settings, name: str, *, allowed: bool = True, sha256: str | None = None
) -> str:
    """Заводит запись реестра сырым SQL: такое имя загрузка не пропустит.

    Хэш берётся у файла на диске: выдача сверяет содержимое открытого файла с
    записью, а запись без хэша закрыта. Специальные файлы не читаются — у них
    хэша нет по определению.
    """
    document_id = str(uuid.uuid4())
    if sha256 is None:
        target = Path(cfg.docs_dir) / name
        sha256 = (
            hashlib.sha256(target.read_bytes()).hexdigest() if target.is_file() else ""
        )
    with sqlite3.connect(_database_path(cfg.database_url)) as connection:
        connection.execute(
            "INSERT INTO corpus_documents"
            " (name, document_id, uploaded_at, sha256, download_allowed)"
            " VALUES (?, ?, '2026-09-22T00:00:00+00:00', ?, ?)",
            (name, document_id, sha256, 1 if allowed else 0),
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


def test_closed_document_stays_searchable_and_needs_no_reindex(tmp_path, sqlite_url):
    """Закрытый для скачивания документ остаётся в поиске и не требует переиндексации.

    Разрешение управляет только выдачей файла: ответы и цитаты по закрытому
    документу работают как раньше. Поэтому поиск проверяется до включения
    флага — иначе сценарий подтверждал бы не то, что заявлено.
    """
    cfg = _cfg(tmp_path, sqlite_url)
    with TestClient(make_app(cfg)) as client:
        _upload(client, "policy.md", POLICY.encode(), index="true")
        row = _row(client, "policy.md")
        download, permission = _urls(row)
        built_at = client.get("/api/v1/admin/documents").json()["built_at"]
        assert row["download_allowed"] is False
        assert client.get(download).status_code == 404

        closed = client.post("/api/v1/search", json={"query": "отпуск", "top_k": 5})
        assert closed.status_code == 200
        assert closed.json()["results"], "закрытый документ должен находиться поиском"

        assert client.patch(permission, json={"download_allowed": True}).status_code == 200

        after = client.get("/api/v1/admin/documents").json()
        assert after["built_at"] == built_at, "разрешение не требует переиндексации"
        assert _row(client, "policy.md")["download_allowed"] is True
        assert client.get(download).content == POLICY.encode()


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


def test_replacement_publishes_new_content_only_after_revoking(
    tmp_path, sqlite_url, monkeypatch
):
    """Новый файл появляется на диске только после снятия разрешения.

    Иначе замена закрытого документа успела бы побывать доступной под прежним
    разрешением: параллельный GET прочитал бы реестр со старым флагом и отдал
    бы уже новый файл.
    """
    from ragkb.db.repos.corpus_documents import PostgresCorpusDocuments

    cfg = _cfg(tmp_path, sqlite_url)
    documents_dir = Path(cfg.docs_dir)
    published: list[bytes] = []
    original_record = PostgresCorpusDocuments.record

    async def spying_record(self, name, **kwargs):
        target = documents_dir / name
        published.append(target.read_bytes() if target.is_file() else b"")
        return await original_record(self, name, **kwargs)

    monkeypatch.setattr(PostgresCorpusDocuments, "record", spying_record)
    with TestClient(make_app(cfg)) as client:
        _upload(client, "spec.pdf", PDF, download_allowed="true")
        published.clear()
        replacement = PDF + "заменено".encode()

        _upload(client, "spec.pdf", replacement)
        row = _row(client, "spec.pdf")
        download, permission = _urls(row)

        assert client.get(download).status_code == 404, "разрешение не наследуется"
        assert client.patch(permission, json={"download_allowed": True}).status_code == 200
        assert client.get(download).content == replacement

    assert published == [PDF], "в момент отзыва на диске должен быть прежний файл"


def test_failed_replacement_does_not_publish_new_content(
    tmp_path, sqlite_url, monkeypatch
):
    """Отказ записи в реестре не оставляет новый контент под старым разрешением."""
    from ragkb.db.repos.corpus_documents import PostgresCorpusDocuments

    cfg = _cfg(tmp_path, sqlite_url)
    with TestClient(make_app(cfg), raise_server_exceptions=False) as client:
        _upload(client, "spec.pdf", PDF, download_allowed="true")
        row = _row(client, "spec.pdf")
        download, _ = _urls(row)

        async def failing_record(self, name, **kwargs):
            raise RuntimeError("база недоступна")

        monkeypatch.setattr(PostgresCorpusDocuments, "record", failing_record)
        replacement = PDF + "закрытая замена".encode()
        failed = client.post(
            "/api/v1/admin/documents",
            params={"index": "false"},
            files={"file": ("spec.pdf", replacement, "application/pdf")},
        )

        assert failed.status_code == 500
        served = client.get(download)
        assert served.content == PDF, "новый контент не должен быть доступен"

    assert [path.name for path in Path(cfg.docs_dir).iterdir()] == ["spec.pdf"]
    lines = _audit_lines(cfg)
    assert len(lines) == 1, lines
    assert "old=false" in lines[0] and "new=true" in lines[0]


async def test_failed_replacement_keeps_old_bytes_under_permission(
    tmp_path, sqlite_url, monkeypatch
):
    """Отказ записи оставляет под прежним разрешением прежний файл.

    Проверка на уровне сервиса: имя уже разрешено, содержимое заменено, а
    запись реестра не сохранилась. Новый файл не публикуется, поэтому выдача
    обязана отдать прежние байты, а не закрытую замену.
    """
    from ragkb.core.database import make_engine, make_session_factory
    from ragkb.core.errors import Conflict
    from ragkb.core.index import ConfigIndex
    from ragkb.db.repos.corpus_documents import PostgresCorpusDocuments
    from ragkb.services.documents import DocumentsService
    from ragkb.services.downloads import DownloadsService

    cfg = _cfg(tmp_path, sqlite_url)
    engine = make_engine(sqlite_url)
    try:
        registry = PostgresCorpusDocuments(make_session_factory(engine))
        documents = DocumentsService(
            cfg, ConfigIndex(cfg, lambda: None), lambda: None, registry
        )
        first = await documents.upload("spec.pdf", PDF, index=False, download_allowed=True)

        async def failing_record(*args, **kwargs):
            raise Conflict("занято другим изменением")

        monkeypatch.setattr(registry, "record", failing_record)
        with pytest.raises(Conflict):
            await documents.upload(
                "spec.pdf", PDF + "закрытая замена".encode(), index=False
            )

        stored = await registry.get_by_id(first.document_id)
        assert stored.download_allowed is True, "прежнее разрешение не менялось"
        assert stored.sha256 == hashlib.sha256(PDF).hexdigest()

        downloads = DownloadsService(Path(cfg.docs_dir), registry)
        descriptor = await downloads.resolve(first.document_id)
        try:
            served = descriptor.handle.read()
        finally:
            descriptor.close()
    finally:
        await engine.dispose()

    assert served == PDF, "выдача не должна отдавать неопубликованную замену"
    assert [path.name for path in Path(cfg.docs_dir).iterdir()] == ["spec.pdf"]


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
            document_id = _seed_registry_row(cfg, name)
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
            document_id = _seed_registry_row(cfg, name)
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


def test_special_file_is_refused_without_blocking(tmp_path, sqlite_url):
    """FIFO в корпусе не должен останавливать цикл событий.

    Открытие такого файла только для чтения ждёт писателя, поэтому конечный
    компонент открывается неблокирующим: запрос получает отказ сразу, а не
    висит до появления данных.
    """
    cfg = _cfg(tmp_path, sqlite_url)
    os.mkfifo(Path(cfg.docs_dir) / "fifo.pdf")
    document_id = _seed_registry_row(cfg, "fifo.pdf")
    # Запрос уходит в отдельный процесс: заблокированное открытие FIFO
    # остановило бы и цикл событий, и завершение тестового клиента, поэтому
    # зависание нужно ограничивать снаружи — как это делает сервер по таймауту.
    script = textwrap.dedent(
        f"""
        import sys
        sys.path[:0] = [{str(BACKEND_ROOT / "tests")!r}, {str(BACKEND_ROOT)!r}]
        from fastapi.testclient import TestClient
        from helpers import make_app
        from ragkb.core.config import Settings

        cfg = Settings(docs_dir={str(cfg.docs_dir)!r}, index_dir={str(cfg.index_dir)!r})
        cfg.store.backend = "memory"
        cfg.database_url = {sqlite_url!r}
        with TestClient(make_app(cfg)) as client:
            response = client.get("/api/v1/documents/{document_id}/download")
            print("STATUS", response.status_code)
        """
    )
    try:
        completed = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            timeout=20,
        )
    except subprocess.TimeoutExpired:
        pytest.fail("выдача заблокировалась на специальном файле")

    assert completed.returncode == 0, completed.stderr
    assert "STATUS 404" in completed.stdout


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
        document_id = _seed_registry_row(cfg, "data.bin")

        response = client.get(f"/api/v1/documents/{document_id}/download")

        assert response.status_code == 200
        assert response.headers["content-type"] == "application/octet-stream"
        assert response.content == b"\x00\x01\x02"


def test_record_without_content_hash_is_not_served(tmp_path, sqlite_url):
    """Запись без хэша закрыта: связать разрешение с байтами нечем."""
    cfg = _cfg(tmp_path, sqlite_url)
    (Path(cfg.docs_dir) / "legacy.pdf").write_bytes(PDF)
    with TestClient(make_app(cfg)) as client:
        document_id = _seed_registry_row(cfg, "legacy.pdf", sha256="")

        response = client.get(f"/api/v1/documents/{document_id}/download")

        assert response.status_code == 404
        assert response.content != PDF


# --------------------------------------------------- содержимое и запись


def test_get_does_not_serve_content_that_replaced_the_record(
    tmp_path, sqlite_url, monkeypatch
):
    """Подмена файла между чтением записи и открытием не выдаётся.

    Разрешение уже прочитано (оно разрешает прежнее содержимое), а на диске к
    моменту открытия лежит другое, закрытое. Выдача сверяет байты открытого
    файла с записью, поэтому такой запрос получает отказ, а не новый файл.
    """
    from ragkb.db.repos.corpus_documents import PostgresCorpusDocuments

    cfg = _cfg(tmp_path, sqlite_url)
    with TestClient(make_app(cfg)) as client:
        _upload(client, "spec.pdf", PDF, download_allowed="true")
        row = _row(client, "spec.pdf")
        download, _ = _urls(row)
        replacement = PDF + "закрытая замена".encode()
        swapped: list[str] = []
        original_get = PostgresCorpusDocuments.get_by_id

        async def get_then_replace(self, document_id):
            document = await original_get(self, document_id)
            if not swapped:
                swapped.append(document_id)
                # Замена мимо интерфейса: файл уже новый, запись ещё прежняя.
                (Path(cfg.docs_dir) / "spec.pdf").write_bytes(replacement)
            return document

        monkeypatch.setattr(PostgresCorpusDocuments, "get_by_id", get_then_replace)
        served = client.get(download)
        monkeypatch.setattr(PostgresCorpusDocuments, "get_by_id", original_get)

    assert swapped == [row["document_id"]]
    assert served.status_code == 404, "новый контент не выдаётся под старым разрешением"
    assert served.content != replacement


def test_opened_file_keeps_its_bytes_when_name_is_replaced(
    tmp_path, sqlite_url, monkeypatch
):
    """Подмена имени не меняет байты уже открытого файла.

    `os.replace` подставляет другой inode: дескриптор, из которого идёт
    выдача, остаётся на прежнем содержимом, и сверка с записью сходится.
    """
    import ragkb.services.downloads as downloads_module

    cfg = _cfg(tmp_path, sqlite_url)
    documents_dir = Path(cfg.docs_dir)
    with TestClient(make_app(cfg)) as client:
        _upload(client, "spec.pdf", PDF, download_allowed="true")
        row = _row(client, "spec.pdf")
        download, _ = _urls(row)
        replacement = PDF + "закрытая замена".encode()
        original_hash = downloads_module._hash_and_rewind

        def hash_after_atomic_replacement(handle):
            staged = documents_dir / ".staged.upload"
            staged.write_bytes(replacement)
            os.replace(staged, documents_dir / "spec.pdf")
            return original_hash(handle)

        monkeypatch.setattr(
            downloads_module, "_hash_and_rewind", hash_after_atomic_replacement
        )
        served = client.get(download)

    assert served.status_code == 200
    assert served.content == PDF, "выдаётся содержимое открытого inode"


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
        # Замена без явного разрешения: в журнал должно попасть то значение,
        # которое запись реально заменила — то есть `false` от PATCH, а не
        # `true` от первой загрузки.
        _upload(client, "spec.pdf", PDF + "заменено".encode())

    lines = _audit_lines(cfg)
    assert any(
        "action=upload" in line and "result=ok" in line and "old=false" in line
        and "new=true" in line
        for line in lines
    ), lines
    assert any(
        "request_id=req-1" in line and "old=true" in line and "new=false" in line
        for line in lines
    ), lines
    assert any(
        "action=replace" in line and "old=false" in line and "new=false" in line
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


def test_permission_change_is_audited_when_indexing_fails(
    tmp_path, sqlite_url, monkeypatch
):
    """Сохранённое разрешение попадает в журнал, даже если индексация упала.

    Загрузка возвращает 503 после того, как запись и файл уже сохранены:
    новый файл скачивается, поэтому событие false→true обязано быть в журнале
    ровно один раз.
    """
    from ragkb.core.errors import EngineUnavailable
    from ragkb.core.index import ConfigIndex

    cfg = _cfg(tmp_path, sqlite_url)

    def failing_rebuild(self, names):
        # Пересборка индекса синхронная: сервис зовёт её в отдельном потоке.
        raise EngineUnavailable("эмбеддер недоступен")

    with TestClient(make_app(cfg)) as client:
        _upload(client, "spec.pdf", PDF)
        row = _row(client, "spec.pdf")
        download, _ = _urls(row)
        assert row["download_allowed"] is False
        assert client.get(download).status_code == 404

        monkeypatch.setattr(ConfigIndex, "rebuild", failing_rebuild)
        replacement = PDF + "замена".encode()
        failed = client.post(
            "/api/v1/admin/documents",
            params={"index": "true", "download_allowed": "true"},
            files={"file": ("spec.pdf", replacement, "application/pdf")},
            headers={"x-request-id": "req-index"},
        )

        assert failed.status_code == 503
        assert _row(client, "spec.pdf")["download_allowed"] is True
        served = client.get(download)
        assert served.status_code == 200
        assert served.content == replacement

    changed = [line for line in _audit_lines(cfg) if "old=false" in line and "new=true" in line]
    assert len(changed) == 1, _audit_lines(cfg)
    assert "action=replace" in changed[0]
    assert "request_id=req-index" in changed[0]
    assert row["document_id"] in changed[0]


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
    document_id = _seed_registry_row(cfg, "big.pdf")
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

# ------------------------------------------------------ сквозной сценарий


def test_answer_attaches_the_original_and_revocation_closes_it(
    tmp_path, sqlite_url, monkeypatch
):
    """Закрытый источник знаний и разрешённый оригинал в одном ответе.

    Ответ строится по закрытому для скачивания документу, а инструмент
    прикладывает разрешённый PDF: карточка ведёт на тот же файл, байты
    совпадают с загруженными, а отзыв разрешения закрывает ссылку.
    """
    from helpers import ScriptedChatModel
    from langchain_core.messages import AIMessage

    from ragkb.api.schemas.ask import DoneEvent
    from ragkb.core.answer_events import TOOL_GET_DOWNLOAD_LINK

    cfg = _cfg(tmp_path, sqlite_url)
    cfg.llm.base_url = "http://llm.test/v1"
    cfg.llm.model = "test-model"

    with TestClient(make_app(cfg)) as client:
        _upload(client, "faq.md", POLICY.encode(), index="true")
        _upload(client, "AdSmart Multi.pdf", PDF, download_allowed="true")
        rows = {row["name"]: row for row in client.get("/api/v1/admin/documents").json()["corpus"]}
        faq, pdf_row = rows["faq.md"], rows["AdSmart Multi.pdf"]
        assert faq["download_allowed"] is False
        assert pdf_row["download_allowed"] is True

        model = ScriptedChatModel(
            responses=[
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": TOOL_GET_DOWNLOAD_LINK,
                            "args": {"document_id": pdf_row["document_id"]},
                            "id": "call-1",
                        }
                    ],
                ),
                AIMessage(content="Требования приложены [1]."),
            ]
        )
        monkeypatch.setattr(
            "ragkb.core.pipeline.build_chat_model", lambda *_args, **_kwargs: model
        )

        response = client.post(
            "/api/v1/ask", json={"question": "Пришли требования к AdSmart Multi"}
        )

        assert response.status_code == 200
        events = [json.loads(line) for line in response.text.splitlines()]
        done = DoneEvent(**events[-1])
        assert [str(item.document_id) for item in done.attachments] == [
            pdf_row["document_id"]
        ]
        assert "приложены" in "".join(event.get("text", "") for event in events)

        attachment = done.attachments[0]
        assert attachment.filename == "AdSmart Multi.pdf"
        # Карточка ведёт на адрес BFF, а байты отдаёт маршрут backend.
        assert attachment.url == f"/api/documents/{pdf_row['document_id']}/download"
        backend_url = f"/api/v1/documents/{pdf_row['document_id']}/download"
        served = client.get(backend_url)
        assert served.status_code == 200
        assert served.content == PDF

        # Отзыв разрешения закрывает и уже выданную ссылку.
        client.patch(
            f"/api/v1/documents/{pdf_row['document_id']}/download-permission",
            json={"download_allowed": False},
        )
        assert client.get(backend_url).status_code == 404
