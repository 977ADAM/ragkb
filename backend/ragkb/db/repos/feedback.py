"""Postgres-адаптер оценок ответов. Схемой владеет Alembic."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ragkb.db.models import (
    ConversationRow,
    MessageFeedbackRow,
    MessageRow,
    UserRow,
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class PostgresFeedback:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory

    async def conversation_owned_by(
        self, conversation_id: str, user: str
    ) -> bool:
        async with self.session_factory() as session:
            row = await session.scalar(
                select(ConversationRow.id).where(
                    ConversationRow.id == conversation_id,
                    ConversationRow.owner == user,
                )
            )
        return row is not None

    async def message_in_conversation(
        self, message_id: int, conversation_id: str
    ) -> bool:
        async with self.session_factory() as session:
            row = await session.scalar(
                select(MessageRow.id).where(
                    MessageRow.id == message_id,
                    MessageRow.conversation_id == conversation_id,
                )
            )
        return row is not None

    async def set_feedback(self, message_id: int, rating: str, comment: str) -> None:
        now = _utcnow()
        async with self.session_factory() as session:
            existing = await session.scalar(
                select(MessageFeedbackRow.id).where(
                    MessageFeedbackRow.message_id == message_id
                )
            )
            if existing is None:
                session.add(
                    MessageFeedbackRow(
                        message_id=message_id,
                        rating=rating,
                        comment=comment,
                        created_at=now,
                        updated_at=now,
                    )
                )
            else:
                await session.execute(
                    update(MessageFeedbackRow)
                    .where(MessageFeedbackRow.message_id == message_id)
                    .values(rating=rating, comment=comment, updated_at=now)
                )
            await session.commit()

    async def counts(self) -> tuple[int, int]:
        async with self.session_factory() as session:
            rows = (
                await session.execute(
                    select(MessageFeedbackRow.rating, func.count())
                    .group_by(MessageFeedbackRow.rating)
                )
            ).all()
        up = down = 0
        for rating, n in rows:
            if rating == "up":
                up = int(n)
            elif rating == "down":
                down = int(n)
        return up, down

    async def list_feedback(
        self, limit: int = 200
    ) -> list[tuple[str, str, str, str, str, str]]:
        async with self.session_factory() as session:
            rows = (
                await session.execute(
                    select(
                        ConversationRow.id,
                        UserRow.username,
                        MessageFeedbackRow.rating,
                        MessageFeedbackRow.comment,
                        MessageRow.text,
                        MessageFeedbackRow.created_at,
                    )
                    .select_from(MessageFeedbackRow)
                    .join(MessageRow, MessageRow.id == MessageFeedbackRow.message_id)
                    .join(
                        ConversationRow,
                        ConversationRow.id == MessageRow.conversation_id,
                    )
                    .join(UserRow, UserRow.username == ConversationRow.owner)
                    .order_by(MessageFeedbackRow.created_at.desc())
                    .limit(limit)
                )
            ).all()
        return [
            (
                conversation_id,
                username,
                rating,
                comment,
                answer,
                created_at.isoformat(),
            )
            for conversation_id, username, rating, comment, answer, created_at in rows
        ]
