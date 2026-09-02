"""Postgres-адаптер истории. Схемой владеет Alembic, здесь только запросы."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ragkb.core.database import assert_revision
from ragkb.db.models import CleanupStateRow, ConversationRow, MessageRow
from ragkb.domain.entities import Conversation, Message


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class PostgresHistory:
    CLEANUP_INTERVAL_DAYS = 1

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        retention_days: int = 90,
    ):
        self.session_factory = session_factory
        self.retention_days = retention_days

    async def ready(self) -> None:
        async with self.session_factory() as session:
            await assert_revision(session)

    async def create(self, user: str) -> str:
        conversation_id = str(uuid.uuid4())
        now = utcnow()
        async with self.session_factory() as session:
            session.add(
                ConversationRow(
                    id=conversation_id,
                    owner=user,
                    title="",
                    created_at=now,
                    updated_at=now,
                )
            )
            await session.commit()
        return conversation_id

    async def append(
        self,
        conversation_id: str,
        user: str,
        role: str,
        text: str,
        sources: list[dict[str, Any]] | None = None,
        model: str = "",
    ) -> int | None:
        now = utcnow()
        async with self.session_factory() as session:
            owner = await session.scalar(
                select(ConversationRow.id).where(
                    ConversationRow.id == conversation_id,
                    ConversationRow.owner == user,
                )
            )
            if owner is None:
                return None
            row = MessageRow(
                conversation_id=conversation_id,
                role=role,
                text=text,
                sources=sources or [],
                created_at=now,
                model=model,
            )
            session.add(row)
            await session.flush()
            message_id = row.id
            await session.execute(
                update(ConversationRow)
                .where(ConversationRow.id == conversation_id)
                .values(updated_at=now)
            )
            await session.commit()
        return message_id

    async def set_title_if_empty(self, conversation_id: str, user: str, title: str) -> bool:
        async with self.session_factory() as session:
            result = await session.execute(
                update(ConversationRow)
                .where(
                    ConversationRow.id == conversation_id,
                    ConversationRow.owner == user,
                    ConversationRow.title == "",
                )
                .values(title=title)
            )
            await session.commit()
        return result.rowcount > 0

    async def owns(self, conversation_id: str, user: str) -> bool:
        async with self.session_factory() as session:
            row = await session.scalar(
                select(ConversationRow.id).where(
                    ConversationRow.id == conversation_id,
                    ConversationRow.owner == user,
                )
            )
        return row is not None

    async def list_conversations(
        self, user: str, limit: int = 50, offset: int = 0
    ) -> list[Conversation]:
        async with self.session_factory() as session:
            rows = (
                await session.execute(
                    select(ConversationRow)
                    .where(ConversationRow.owner == user)
                    .order_by(ConversationRow.updated_at.desc())
                    .limit(limit)
                    .offset(offset)
                )
            ).scalars().all()
        return [
            Conversation(
                row.id,
                row.title,
                row.created_at.isoformat(),
                row.updated_at.isoformat(),
            )
            for row in rows
        ]

    async def count_conversations(self, user: str) -> int:
        async with self.session_factory() as session:
            total = await session.scalar(
                select(func.count()).select_from(ConversationRow).where(
                    ConversationRow.owner == user
                )
            )
        return int(total or 0)

    async def get_messages(self, conversation_id: str, user: str) -> list[Message] | None:
        async with self.session_factory() as session:
            owner = await session.scalar(
                select(ConversationRow.id).where(
                    ConversationRow.id == conversation_id,
                    ConversationRow.owner == user,
                )
            )
            if owner is None:
                return None
            rows = (
                await session.execute(
                    select(MessageRow)
                    .where(MessageRow.conversation_id == conversation_id)
                    .order_by(MessageRow.id)
                )
            ).scalars().all()
        return [
            Message(
                id=row.id,
                role=row.role,
                text=row.text,
                created_at=row.created_at.isoformat(),
                sources=list(row.sources or []),
                model=row.model,
            )
            for row in rows
        ]

    async def recent_turns(
        self, conversation_id: str, user: str, window: int
    ) -> list[tuple[str, str]]:
        if window <= 0:
            return []
        async with self.session_factory() as session:
            owner = await session.scalar(
                select(ConversationRow.id).where(
                    ConversationRow.id == conversation_id,
                    ConversationRow.owner == user,
                )
            )
            if owner is None:
                return []
            rows = (
                await session.execute(
                    select(MessageRow)
                    .where(MessageRow.conversation_id == conversation_id)
                    .order_by(MessageRow.id.desc())
                    .limit(window * 2 + 1)
                )
            ).scalars().all()
        turns: list[tuple[str, str]] = []
        pending: str | None = None
        for row in reversed(rows):
            if row.role == "user":
                pending = row.text
            elif pending is not None:
                turns.append((pending, row.text))
                pending = None
        return turns[-window:]

    async def rename(self, conversation_id: str, user: str, title: str) -> bool:
        async with self.session_factory() as session:
            result = await session.execute(
                update(ConversationRow)
                .where(
                    ConversationRow.id == conversation_id,
                    ConversationRow.owner == user,
                )
                .values(title=title)
            )
            await session.commit()
        return result.rowcount > 0

    async def delete(self, conversation_id: str, user: str) -> bool:
        async with self.session_factory() as session:
            result = await session.execute(
                delete(ConversationRow).where(
                    ConversationRow.id == conversation_id,
                    ConversationRow.owner == user,
                )
            )
            await session.commit()
        return result.rowcount > 0

    async def remove_message(self, message_id: int, user: str) -> bool:
        async with self.session_factory() as session:
            result = await session.execute(
                delete(MessageRow).where(
                    MessageRow.id == message_id,
                    MessageRow.conversation_id.in_(
                        select(ConversationRow.id).where(ConversationRow.owner == user)
                    ),
                )
            )
            await session.commit()
        return result.rowcount > 0

    async def cleanup(self, now: datetime | None = None, batch: int = 500) -> int:
        now = now or utcnow()
        due_before = now - timedelta(days=self.CLEANUP_INTERVAL_DAYS)
        expired_before = now - timedelta(days=self.retention_days)
        async with self.session_factory() as session:
            claimed = await session.execute(
                update(CleanupStateRow)
                .where(
                    CleanupStateRow.id == 1,
                    CleanupStateRow.last_run < due_before,
                )
                .values(last_run=now)
            )
            if claimed.rowcount == 0:
                await session.rollback()
                return 0
            ids = (
                await session.execute(
                    select(ConversationRow.id)
                    .where(ConversationRow.updated_at < expired_before)
                    .limit(batch)
                )
            ).scalars().all()
            if not ids:
                await session.commit()
                return 0
            await session.execute(
                delete(ConversationRow).where(ConversationRow.id.in_(ids))
            )
            if len(ids) == batch:
                await session.execute(
                    update(CleanupStateRow)
                    .where(CleanupStateRow.id == 1)
                    .values(last_run=datetime(1970, 1, 1, tzinfo=timezone.utc))
                )
            await session.commit()
        return len(ids)
