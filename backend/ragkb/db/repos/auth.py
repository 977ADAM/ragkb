"""Postgres-адаптер аккаунтов и сессий."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ragkb.core.database import assert_revision
from ragkb.db.models import SessionRow, UserRow
from ragkb.platform.errors import Conflict


class PostgresAccounts:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory

    async def ready(self) -> None:
        async with self.session_factory() as session:
            await assert_revision(session)

    async def create_user(self, username: str, password_hash: str) -> str:
        user_id = str(uuid.uuid4())
        async with self.session_factory() as session:
            session.add(
                UserRow(
                    id=user_id,
                    username=username,
                    password_hash=password_hash,
                    created_at=datetime.now(timezone.utc),
                )
            )
            try:
                await session.commit()
            except IntegrityError as exc:
                raise Conflict("Такой логин уже занят") from exc
        return user_id

    async def get_by_username(self, username: str) -> tuple[str, str, str] | None:
        async with self.session_factory() as session:
            row = await session.scalar(
                select(UserRow).where(UserRow.username == username)
            )
        if row is None:
            return None
        return (row.id, row.username, row.password_hash)

    async def create_session(
        self, user_id: str, token_hash: str, expires_at: str
    ) -> None:
        expires = datetime.fromisoformat(expires_at)
        async with self.session_factory() as session:
            session.add(
                SessionRow(
                    token_hash=token_hash,
                    user_id=user_id,
                    expires_at=expires,
                )
            )
            await session.commit()

    async def delete_session(self, token_hash: str) -> None:
        async with self.session_factory() as session:
            await session.execute(
                delete(SessionRow).where(SessionRow.token_hash == token_hash)
            )
            await session.commit()

    async def user_for_token_hash(self, token_hash: str) -> tuple[str, str] | None:
        now = datetime.now(timezone.utc)
        async with self.session_factory() as session:
            row = await session.scalar(
                select(UserRow)
                .join(SessionRow, SessionRow.user_id == UserRow.id)
                .where(
                    SessionRow.token_hash == token_hash,
                    SessionRow.expires_at >= now,
                )
            )
        if row is None:
            return None
        return (row.id, row.username)
