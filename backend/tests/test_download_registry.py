"""Реестр корпуса: идентификатор документа и разрешение на выдачу оригинала.

Реестр получает `document_id` (UUID строкой) и `download_allowed` (по умолчанию
выключено). Идентификатор стабилен при замене файла и исчезает вместе с
записью, а разрешение при замене не наследуется молча: его задаёт явный
параметр загрузки. Оба адаптера — SQLAlchemy и MemoryRegistry — обязаны вести
себя одинаково, поэтому сценарии прогоняются на обоих.

Миграция 0002 обязана пройти по существующей базе, не потеряв ни документы,
ни посторонние таблицы: прежние записи получают разные идентификаторы и
выключенное разрешение.
"""
from __future__ import annotations

import asyncio
import contextlib
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.config import Config as AlembicConfig
from helpers import BACKEND_ROOT, MemoryRegistry
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ragkb.core.database import (
    EXPECTED_REVISION,
    alembic_sync_url,
    assert_revision,
    make_engine,
    make_session_factory,
)
from ragkb.db.repos.corpus_documents import PostgresCorpusDocuments
from ragkb.domain.entities import ORIGIN_UI

SEED = (
    ("a.pdf", 11, "a" * 64),
    ("b.docx", 22, "b" * 64),
)




def _sqlite_url(tmp_path: Path) -> str:
    return f"sqlite+aiosqlite:///{tmp_path / 'registry.sqlite3'}"


def _alembic_config() -> AlembicConfig:
    cfg = AlembicConfig(str(BACKEND_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_ROOT / "migrations"))
    return cfg


def _migrate(url: str, revision: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RAGKB_DATABASE_URL", url)
    command.upgrade(_alembic_config(), revision)


def _downgrade(url: str, revision: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RAGKB_DATABASE_URL", url)
    command.downgrade(_alembic_config(), revision)


def _migrated_sqlite(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    """База, собранная единственной миграцией: полная схема реестра."""
    url = _sqlite_url(tmp_path)
    _migrate(url, "head", monkeypatch)
    return url


def _connect(url: str):
    return create_engine(alembic_sync_url(url))


def _columns(url: str) -> set[str]:
    engine = _connect(url)
    try:
        with engine.connect() as conn:
            return {row[1] for row in conn.execute(text("PRAGMA table_info(corpus_documents)"))}
    finally:
        engine.dispose()


def _insert(url: str, name: str, document_id: str, **flags: Any) -> None:
    engine = _connect(url)
    try:
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO corpus_documents"
                    " (name, document_id, uploaded_at, size, sha256,"
                    "  download_allowed, index_enabled)"
                    " VALUES (:name, :document_id, '2026-09-22T00:00:00+00:00', 10, :sha256,"
                    "  :download_allowed, :index_enabled)"
                ),
                {
                    "name": name,
                    "document_id": document_id,
                    "sha256": "a" * 64,
                    "download_allowed": flags.get("download_allowed", False),
                    "index_enabled": flags.get("index_enabled", True),
                },
            )
    finally:
        engine.dispose()


def _is_uuid(value: Any) -> bool:
    try:
        uuid.UUID(str(value))
    except (TypeError, ValueError):
        return False
    return True


def test_initial_schema_carries_both_switches(tmp_path, monkeypatch):
    """Единственная миграция создаёт схему целиком: ID и два переключателя."""
    url = _migrated_sqlite(tmp_path, monkeypatch)
    assert _columns(url) == {
        "name",
        "document_id",
        "origin",
        "uploaded_by",
        "uploaded_at",
        "size",
        "sha256",
        "download_allowed",
        "index_enabled",
    }

    engine = _connect(url)
    try:
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO corpus_documents (name, document_id, uploaded_at)"
                    " VALUES ('defaults.pdf', :document_id, '2026-09-22T00:00:00+00:00')"
                ),
                {"document_id": str(uuid.uuid4())},
            )
            row = conn.execute(
                text(
                    "SELECT download_allowed, index_enabled FROM corpus_documents"
                    " WHERE name = 'defaults.pdf'"
                )
            ).one()
            assert (bool(row[0]), bool(row[1])) == (False, True)
            with pytest.raises(IntegrityError):
                conn.execute(
                    text(
                        "INSERT INTO corpus_documents (name, uploaded_at)"
                        " VALUES ('no-id.pdf', '2026-09-22T00:00:00+00:00')"
                    )
                )
    finally:
        engine.dispose()


def test_identifiers_are_unique(tmp_path, monkeypatch):
    url = _migrated_sqlite(tmp_path, monkeypatch)
    shared = str(uuid.uuid4())
    _insert(url, "a.pdf", shared)
    with pytest.raises(IntegrityError):
        _insert(url, "b.pdf", shared)


def test_upgrade_is_idempotent_and_keeps_foreign_tables(tmp_path, monkeypatch):
    url = _migrated_sqlite(tmp_path, monkeypatch)
    document_id = str(uuid.uuid4())
    _insert(url, "a.pdf", document_id, download_allowed=True, index_enabled=False)
    engine = _connect(url)
    try:
        with engine.begin() as conn:
            conn.execute(text("CREATE TABLE legacy_accounts (id INTEGER PRIMARY KEY, login TEXT)"))
            conn.execute(text("INSERT INTO legacy_accounts (id, login) VALUES (1, 'ada')"))
    finally:
        engine.dispose()

    _migrate(url, "head", monkeypatch)

    engine = _connect(url)
    try:
        with engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT document_id, download_allowed, index_enabled"
                    " FROM corpus_documents WHERE name = 'a.pdf'"
                )
            ).one()
            assert row[0] == document_id
            assert (bool(row[1]), bool(row[2])) == (True, False)
            assert conn.execute(text("SELECT login FROM legacy_accounts")).scalar() == "ada"
            assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar() == (
                EXPECTED_REVISION
            )
    finally:
        engine.dispose()


def test_migrated_database_reports_expected_revision(tmp_path, monkeypatch):
    url = _migrated_sqlite(tmp_path, monkeypatch)
    engine = make_engine(url)
    try:
        session_factory = make_session_factory(engine)
        asyncio.run(_assert_revision(session_factory))
    finally:
        asyncio.run(engine.dispose())


async def _assert_revision(session_factory) -> None:
    async with session_factory() as session:
        await assert_revision(session)


def test_downgrade_drops_only_the_registry(tmp_path, monkeypatch):
    """Откат начальной миграции убирает реестр — это её собственная таблица."""
    url = _migrated_sqlite(tmp_path, monkeypatch)
    _insert(url, "a.pdf", str(uuid.uuid4()))

    _downgrade(url, "base", monkeypatch)
    assert _columns(url) == set()
    _migrate(url, "head", monkeypatch)
    engine = _connect(url)
    try:
        with engine.connect() as conn:
            assert conn.execute(text("SELECT count(*) FROM corpus_documents")).scalar() == 0
    finally:
        engine.dispose()


@asynccontextmanager
async def _sqlite_registry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Мигрированная временная SQLite и адаптер реестра поверх неё."""
    url = _sqlite_url(tmp_path)
    _migrate(url, "head", monkeypatch)
    engine = make_engine(url)
    try:
        yield PostgresCorpusDocuments(make_session_factory(engine))
    finally:
        await engine.dispose()


async def _contract(registry) -> None:
    """Сценарий, одинаковый для SQLAlchemy-адаптера и MemoryRegistry."""
    recorded = await registry.record(
        "spec.pdf", origin=ORIGIN_UI, uploaded_by="ada", size=10, sha256="c" * 64
    )
    assert recorded.created is True
    assert recorded.previous_download_allowed is False
    saved = recorded.document
    assert _is_uuid(saved.document_id), "новая запись получает идентификатор"
    assert saved.download_allowed is False

    previous, allowed = await registry.set_download_allowed(saved.document_id, True)
    assert previous is False
    assert allowed.download_allowed is True
    assert (await registry.get_by_id(saved.document_id)).download_allowed is True
    assert recorded.document.index_enabled is True
    assert await registry.index_names() == {"spec.pdf"}
    previous_index, indexed = await registry.set_index_enabled(saved.document_id, False)
    assert (previous_index, indexed.index_enabled) == (True, False)
    assert await registry.index_names() == set()
    assert (await registry.get_by_id(saved.document_id)).index_enabled is False
    assert await registry.set_index_enabled("нет-такого-id", True) is None

    replaced = await registry.record(
        "spec.pdf",
        origin=ORIGIN_UI,
        uploaded_by="ada",
        size=20,
        sha256="d" * 64,
        index_enabled=True,
    )
    assert replaced.created is False
    assert replaced.previous_download_allowed is True
    assert replaced.document.download_allowed is False
    assert replaced.previous_index_enabled is False
    assert replaced.document.index_enabled is True
    current = await registry.get_by_id(saved.document_id)
    assert current is not None
    assert current.document_id == saved.document_id
    assert current.size == 20
    assert current.download_allowed is False
    assert await registry.forget("spec.pdf") is True
    assert await registry.get_by_id(saved.document_id) is None
    assert await registry.set_download_allowed(saved.document_id, True) is None
    await registry.record("spec.pdf")
    again = (await registry.list_all())[0]
    assert again.document_id != saved.document_id


async def test_replace_resets_permission_and_keeps_id():
    await _contract(MemoryRegistry())


async def test_memory_registry_ids_are_unique_per_document():
    registry = MemoryRegistry()
    await registry.record("one.pdf")
    await registry.record("two.pdf")

    ids = [doc.document_id for doc in await registry.list_all()]
    assert len(set(ids)) == 2
    assert await registry.get_by_id("не-uuid") is None


async def test_sqlalchemy_registry_matches_memory_contract(tmp_path, monkeypatch):
    async with _sqlite_registry(tmp_path, monkeypatch) as registry:
        await _contract(registry)


async def test_sequential_permission_changes_report_previous_values(tmp_path, monkeypatch):
    """Прежнее значение — то, что реально заменено, а не прочитано заранее."""
    async with _sqlite_registry(tmp_path, monkeypatch) as registry:
        await registry.record("spec.pdf")
        document = (await registry.list_all())[0]

        first = await registry.set_download_allowed(document.document_id, True)
        second = await registry.set_download_allowed(document.document_id, False)
        third = await registry.set_download_allowed(document.document_id, False)
        assert (first[0], first[1].download_allowed) == (False, True)
        assert (second[0], second[1].download_allowed) == (True, False)
        assert (third[0], third[1].download_allowed) == (False, False)
        assert await registry.set_download_allowed("нет-такого-id", True) is None


async def test_simultaneous_permission_changes_report_distinct_previous_values(
    tmp_path, monkeypatch
):
    """Два одновременных изменения не возвращают одно и то же прежнее значение.

    Обе операции стартуют вместе, а после первого чтения ждут второго чтения
    ограниченное время. Ограничение обязательно: исправленная версия держит
    блокировку записи SQLite до конца изменения, поэтому второго чтения до
    этого момента не будет — ожидание истекает, и это не взаимная блокировка,
    а признак того, что чтение и запись сериализованы. Без блокировки вторая
    операция успевает прочитать `false` до первой записи, и оба изменения
    сообщают одно и то же прежнее значение.
    """
    async with _sqlite_registry(tmp_path, monkeypatch) as registry:
        await registry.record("spec.pdf")
        document = (await registry.list_all())[0]
        started = 0
        release = asyncio.Event()
        reads = 0
        second_read = asyncio.Event()
        working_scalar = AsyncSession.scalar

        async def scalar_noticing_read(self, statement, *args, **kwargs):
            nonlocal reads
            result = await working_scalar(self, statement, *args, **kwargs)
            if "document_id" not in str(statement):
                return result
            reads += 1
            if reads == 1:
                with contextlib.suppress(asyncio.TimeoutError):
                    await asyncio.wait_for(second_read.wait(), timeout=0.5)
            else:
                second_read.set()
            return result

        async def change():
            nonlocal started
            started += 1
            await release.wait()
            return await registry.set_download_allowed(document.document_id, True)

        monkeypatch.setattr(AsyncSession, "scalar", scalar_noticing_read)
        tasks = [asyncio.create_task(change()) for _ in range(2)]
        while started < 2:
            await asyncio.sleep(0)
        release.set()
        results = await asyncio.gather(*tasks)
        monkeypatch.setattr(AsyncSession, "scalar", working_scalar)
        assert reads == 2
        assert sorted(result[0] for result in results) == [False, True]
        assert all(result[1].download_allowed is True for result in results)
        assert (await registry.get_by_id(document.document_id)).download_allowed is True


async def test_failed_permission_change_keeps_value_and_releases_lock(tmp_path, monkeypatch):
    """Отказ записи откатывает изменение и не оставляет блокировку записи."""
    async with _sqlite_registry(tmp_path, monkeypatch) as registry:
        await registry.record("spec.pdf")
        document = (await registry.list_all())[0]
        working_commit = AsyncSession.commit

        async def failing_commit(self):
            raise RuntimeError("запись не удалась")

        monkeypatch.setattr(AsyncSession, "commit", failing_commit)
        with pytest.raises(RuntimeError):
            await registry.set_download_allowed(document.document_id, True)
        monkeypatch.setattr(AsyncSession, "commit", working_commit)
        assert (await registry.get_by_id(document.document_id)).download_allowed is False
        previous, saved = await registry.set_download_allowed(document.document_id, True)
        assert (previous, saved.download_allowed) == (False, True)


async def test_simultaneous_replacement_and_permission_change_agree(tmp_path, monkeypatch):
    """Замена файла и смена флага не читают строку до чужой записи.

    Оба изменения снимают разрешение, а до них оно было выдано: значит,
    включённое разрешение обязан увидеть ровно один из двух — тот, кто записал
    первым. Если бы обе операции читали строку до чужой записи, обе увидели бы
    `true`, и журнал показал бы два отзыва уже снятого разрешения.

    Ожидание после первого чтения ограничено: под корректной блокировкой
    второе чтение до конца первой операции невозможно, поэтому ожидание
    истекает — это не взаимная блокировка.
    """
    async with _sqlite_registry(tmp_path, monkeypatch) as registry:
        await registry.record("spec.pdf", download_allowed=True)
        document = (await registry.list_all())[0]
        started = 0
        release = asyncio.Event()
        reads = 0
        second_read = asyncio.Event()
        working_scalar = AsyncSession.scalar
        working_get = AsyncSession.get

        async def pause_after_read() -> None:
            nonlocal reads
            reads += 1
            if reads == 1:
                with contextlib.suppress(asyncio.TimeoutError):
                    await asyncio.wait_for(second_read.wait(), timeout=0.5)
            else:
                second_read.set()

        async def noticing_scalar(self, statement, *args, **kwargs):
            result = await working_scalar(self, statement, *args, **kwargs)
            if "document_id" in str(statement):
                await pause_after_read()
            return result

        async def noticing_get(self, entity, ident, *args, **kwargs):
            result = await working_get(self, entity, ident, *args, **kwargs)
            await pause_after_read()
            return result

        async def replace():
            nonlocal started
            started += 1
            await release.wait()
            return await registry.record("spec.pdf")

        async def revoke():
            nonlocal started
            started += 1
            await release.wait()
            return await registry.set_download_allowed(document.document_id, False)

        monkeypatch.setattr(AsyncSession, "scalar", noticing_scalar)
        monkeypatch.setattr(AsyncSession, "get", noticing_get)
        tasks = [asyncio.create_task(replace()), asyncio.create_task(revoke())]
        while started < 2:
            await asyncio.sleep(0)
        release.set()
        replacement, permission = await asyncio.gather(*tasks)
        monkeypatch.setattr(AsyncSession, "scalar", working_scalar)
        monkeypatch.setattr(AsyncSession, "get", working_get)
        final = (await registry.get_by_id(document.document_id)).download_allowed
    assert reads == 2
    assert sorted([replacement.previous_download_allowed, permission[0]]) == [False, True]
    assert final is False
    assert replacement.document.download_allowed is False
    assert permission[1].download_allowed is False
