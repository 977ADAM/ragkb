"""Postgres-адаптер реестра документов корпуса. Схемой владеет Alembic."""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ragkb.db.models import CorpusDocumentRow
from ragkb.domain.entities import ORIGIN_UI, CorpusDocument


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


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

        Строка читается с блокировкой и меняется в той же транзакции: прежнее
        значение нельзя вычислять отдельным чтением до записи — иначе два
        одновременных изменения вернули бы одно и то же «старое» значение.
        """
        if not document_id:
            return None
        async with self.session_factory() as session:
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
