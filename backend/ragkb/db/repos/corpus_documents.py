"""Postgres-адаптер реестра документов корпуса. Схемой владеет Alembic."""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ragkb.db.models import CorpusDocumentRow
from ragkb.domain.entities import ORIGIN_UI, CorpusDocument


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def _lock_document_write(session: AsyncSession) -> None:
    """Берёт блокировку записи до чтения строки — на SQLite.

    `SELECT ... FOR UPDATE` SQLite игнорирует, а драйвер pysqlite открывает
    транзакцию только перед первой записью: чтение прошло бы вне транзакции,
    и два одновременных изменения прочитали бы одно и то же прежнее значение.
    В журнале оказались бы две одинаковые пары old/new, хотя одно из значений
    уже заменил другой запрос.

    `BEGIN IMMEDIATE` берёт блокировку записи сразу, поэтому чтение и запись
    становятся одной сериализованной операцией. В Postgres ту же роль играет
    `FOR UPDATE` в самом запросе: второй запрос ждёт строку, а не читает её.

    Если блокировку не удаётся взять за busy timeout драйвера, изменение
    отклоняется ошибкой базы, а не отдаёт неверное прежнее значение: молчаливая
    потеря одной замены в журнале хуже видимой ошибки.
    """
    if session.get_bind().dialect.name == "sqlite":
        await session.execute(text("BEGIN IMMEDIATE"))


class PostgresCorpusDocuments:
    """Реестр принятых в корпус документов.

    Имя документа — путь относительно каталога корпуса, поэтому запись
    находится по одному ключу и переживает перенос каталога индекса.
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory

    async def names(self) -> set[str]:
        async with self.session_factory() as session:
            rows = (await session.execute(select(CorpusDocumentRow.name))).scalars().all()
        return set(rows)

    async def list_all(self) -> list[CorpusDocument]:
        async with self.session_factory() as session:
            rows = (
                (
                    await session.execute(
                        select(CorpusDocumentRow).order_by(
                            CorpusDocumentRow.uploaded_at.desc()
                        )
                    )
                )
                .scalars()
                .all()
            )
        return [row.to_domain() for row in rows]

    async def get_by_id(self, document_id: str) -> CorpusDocument | None:
        if not document_id:
            return None
        async with self.session_factory() as session:
            row = await session.scalar(
                select(CorpusDocumentRow).where(
                    CorpusDocumentRow.document_id == document_id
                )
            )
        return row.to_domain() if row is not None else None

    async def record(
        self,
        name: str,
        *,
        origin: str = ORIGIN_UI,
        uploaded_by: str = "",
        size: int = 0,
        sha256: str = "",
        download_allowed: bool = False,
    ) -> None:
        """Заводит документ или обновляет сведения о нём.

        Повторная загрузка того же имени перезаписывает запись: для корпуса
        это тот же документ, новая версия файла. Идентификатор при этом
        сохраняется, а разрешение берётся из аргумента — прежнее значение
        молча не наследуется.
        """
        async with self.session_factory() as session:
            row = await session.get(CorpusDocumentRow, name)
            if row is None:
                session.add(
                    CorpusDocumentRow(
                        name=name,
                        document_id=str(uuid4()),
                        origin=origin,
                        uploaded_by=uploaded_by,
                        uploaded_at=_utcnow(),
                        size=size,
                        sha256=sha256,
                        download_allowed=download_allowed,
                    )
                )
            else:
                row.origin = origin
                row.uploaded_by = uploaded_by
                row.uploaded_at = _utcnow()
                row.size = size
                row.sha256 = sha256
                row.download_allowed = download_allowed
            await session.commit()

    async def set_download_allowed(
        self, document_id: str, allowed: bool
    ) -> tuple[bool, CorpusDocument] | None:
        """Меняет разрешение и возвращает прежнее значение с записью.

        Чтение прежнего значения и запись нового — одна сериализованная
        операция: на SQLite её открывает `BEGIN IMMEDIATE` (см.
        `_lock_document_write`), на Postgres — блокировка строки `FOR UPDATE`.
        Иначе два одновременных изменения вернули бы одно и то же «старое»
        значение, и журнал соврал бы про одну из замен.
        """
        if not document_id:
            return None
        async with self.session_factory() as session:
            await _lock_document_write(session)
            row = await session.scalar(
                select(CorpusDocumentRow)
                .where(CorpusDocumentRow.document_id == document_id)
                .with_for_update()
            )
            if row is None:
                return None
            previous = bool(row.download_allowed)
            row.download_allowed = bool(allowed)
            await session.commit()
            return previous, row.to_domain()

    async def forget(self, name: str) -> bool:
        async with self.session_factory() as session:
            existing = await session.scalar(
                select(CorpusDocumentRow.name).where(CorpusDocumentRow.name == name)
            )
            if existing is None:
                return False
            await session.execute(
                delete(CorpusDocumentRow).where(CorpusDocumentRow.name == name)
            )
            await session.commit()
        return True
