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

FIRST_REVISION = "0001_corpus_documents"

SEED = (
    ("a.pdf", 11, "a" * 64),
    ("b.docx", 22, "b" * 64),
)


# --------------------------------------------------------------- миграции


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


def _seed_at_0001(url: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """База на 0001 с документами и посторонней таблицей — как у заказчика."""
    _migrate(url, FIRST_REVISION, monkeypatch)
    engine = create_engine(alembic_sync_url(url))
    try:
        with engine.begin() as conn:
            for name, size, sha256 in SEED:
                conn.execute(
                    text(
                        "INSERT INTO corpus_documents"
                        " (name, origin, uploaded_by, uploaded_at, size, sha256)"
                        " VALUES (:name, 'ui', 'ada', '2026-09-10T00:00:00+00:00',"
                        " :size, :sha256)"
                    ),
                    {"name": name, "size": size, "sha256": sha256},
                )
            # Схему аккаунтов миграция не создаёт — но и не удаляет чужое.
            conn.execute(text("CREATE TABLE legacy_accounts (id INTEGER PRIMARY KEY, login TEXT)"))
            conn.execute(text("INSERT INTO legacy_accounts (id, login) VALUES (1, 'ada')"))
    finally:
        engine.dispose()


def _rows(url: str) -> list[Any]:
    engine = create_engine(alembic_sync_url(url))
    try:
        with engine.connect() as conn:
            return list(
                conn.execute(
                    text(
                        "SELECT name, document_id, download_allowed"
                        " FROM corpus_documents ORDER BY name"
                    )
                ).all()
            )
    finally:
        engine.dispose()


def _columns(url: str) -> set[str]:
    engine = create_engine(alembic_sync_url(url))
    try:
        with engine.connect() as conn:
            return {row[1] for row in conn.execute(text("PRAGMA table_info(corpus_documents)"))}
    finally:
        engine.dispose()


def _is_uuid(value: Any) -> bool:
    try:
        uuid.UUID(str(value))
    except (TypeError, ValueError):
        return False
    return True


def test_upgrade_from_0001_keeps_documents_and_closes_downloads(tmp_path, monkeypatch):
    url = _sqlite_url(tmp_path)
    _seed_at_0001(url, monkeypatch)

    _migrate(url, "head", monkeypatch)

    rows = _rows(url)
    assert [row.name for row in rows] == ["a.pdf", "b.docx"]
    assert len({row.document_id for row in rows}) == 2, "идентификаторы должны быть разными"
    assert all(_is_uuid(row.document_id) for row in rows)
    assert all(not row.download_allowed for row in rows), "прежние документы закрыты"
    engine = create_engine(alembic_sync_url(url))
    try:
        with engine.connect() as conn:
            assert conn.execute(text("SELECT login FROM legacy_accounts")).scalar() == "ada"
            assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar() == (
                EXPECTED_REVISION
            )
    finally:
        engine.dispose()


def test_repeated_upgrade_keeps_identifiers(tmp_path, monkeypatch):
    url = _sqlite_url(tmp_path)
    _seed_at_0001(url, monkeypatch)
    _migrate(url, "head", monkeypatch)
    before = {row.name: row.document_id for row in _rows(url)}

    _migrate(url, "head", monkeypatch)

    assert {row.name: row.document_id for row in _rows(url)} == before


def test_downgrade_and_upgrade_keep_documents(tmp_path, monkeypatch):
    url = _sqlite_url(tmp_path)
    _seed_at_0001(url, monkeypatch)
    _migrate(url, "head", monkeypatch)

    _downgrade(url, FIRST_REVISION, monkeypatch)

    # Откат уносит только новые столбцы: идентификатор хранится в них же.
    assert _columns(url) == {"name", "origin", "uploaded_by", "uploaded_at", "size", "sha256"}
    engine = create_engine(alembic_sync_url(url))
    try:
        with engine.connect() as conn:
            assert conn.execute(text("SELECT count(*) FROM corpus_documents")).scalar() == 2
            assert conn.execute(text("SELECT login FROM legacy_accounts")).scalar() == "ada"
    finally:
        engine.dispose()

    _migrate(url, "head", monkeypatch)

    rows = _rows(url)
    assert [row.name for row in rows] == ["a.pdf", "b.docx"]
    assert all(_is_uuid(row.document_id) for row in rows)
    assert all(not row.download_allowed for row in rows)


def test_new_rows_require_identifier_and_default_to_disallowed(tmp_path, monkeypatch):
    url = _sqlite_url(tmp_path)
    _migrate(url, "head", monkeypatch)
    engine = create_engine(alembic_sync_url(url))
    try:
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO corpus_documents"
                    " (name, document_id, uploaded_at) VALUES ('c.md', :id, '2026-09-10T00:00:00')"
                ),
                {"id": str(uuid.uuid4())},
            )
            # Умолчание задаёт схема, а не приложение: без него старые версии
            # кода открыли бы выдачу оригинала.
            assert not conn.execute(
                text("SELECT download_allowed FROM corpus_documents WHERE name = 'c.md'")
            ).scalar()
        with pytest.raises(IntegrityError), engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO corpus_documents (name, uploaded_at)"
                    " VALUES ('d.md', '2026-09-10T00:00:00')"
                )
            )
        with pytest.raises(IntegrityError), engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO corpus_documents (name, document_id, uploaded_at)"
                    " VALUES ('e.md', :id, '2026-09-10T00:00:00')"
                ),
                {"id": _rows(url)[0].document_id},
            )
    finally:
        engine.dispose()


async def test_migrated_database_reports_expected_revision(tmp_path, monkeypatch):
    url = _sqlite_url(tmp_path)
    _migrate(url, "head", monkeypatch)
    engine = make_engine(url)
    try:
        async with make_session_factory(engine)() as session:
            await assert_revision(session)
    finally:
        await engine.dispose()


# ------------------------------------------------- реестр: общий контракт


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
    await registry.record(
        "spec.pdf", origin=ORIGIN_UI, uploaded_by="ada", size=10, sha256="c" * 64
    )
    saved = next(doc for doc in await registry.list_all() if doc.name == "spec.pdf")
    assert _is_uuid(saved.document_id), "новая запись получает идентификатор"
    assert saved.download_allowed is False

    previous, allowed = await registry.set_download_allowed(saved.document_id, True)
    assert previous is False
    assert allowed.download_allowed is True
    assert (await registry.get_by_id(saved.document_id)).download_allowed is True

    # Замена файла: тот же документ, новая версия — идентификатор сохраняется,
    # а разрешение берётся из явного параметра, а не из прежней записи.
    await registry.record(
        "spec.pdf", origin=ORIGIN_UI, uploaded_by="ada", size=20, sha256="d" * 64
    )
    replaced = await registry.get_by_id(saved.document_id)
    assert replaced is not None
    assert replaced.document_id == saved.document_id
    assert replaced.size == 20
    assert replaced.download_allowed is False

    # Удаление: идентификатор перестаёт работать, повторная загрузка даёт новый.
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
