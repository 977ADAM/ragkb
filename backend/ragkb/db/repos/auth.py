"""Postgres-адаптер аккаунтов и сессий."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import delete, func, select
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

    async def create_user(
        self, username: str, password_hash: str, role: str = "user"
    ) -> str:
        user_id = str(uuid.uuid4())
        async with self.session_factory() as session:
            session.add(
                UserRow(
                    id=user_id,
                    username=username,
                    password_hash=password_hash,
                    created_at=datetime.now(timezone.utc),
                    role=role,
                )
            )
            try:
                await session.commit()
            except IntegrityError as exc:
                raise Conflict("Такой логин уже занят") from exc
        return user_id

    async def get_by_username(self, username: str) -> tuple[str, str, str, str] | None:
        async with self.session_factory() as session:
            row = await session.scalar(
                select(UserRow).where(UserRow.username == username)
            )
        if row is None:
            return None
        return (row.id, row.username, row.password_hash, row.role)

    async def update_password(self, username: str, password_hash: str) -> None:
        async with self.session_factory() as session:
            row = await session.scalar(
                select(UserRow).where(UserRow.username == username)
            )
            if row is None:
                return
            row.password_hash = password_hash
            await session.commit()

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

    async def user_for_token_hash(self, token_hash: str) -> tuple[str, str, str] | None:
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
        return (row.id, row.username, row.role)

    async def list_users(self) -> list[tuple[str, str, datetime]]:
        async with self.session_factory() as session:
            rows = (
                await session.scalars(
                    select(UserRow).order_by(UserRow.created_at, UserRow.username)
                )
            ).all()
        return [(row.username, row.role, row.created_at) for row in rows]

    async def set_role(
        self, username: str, role: str
    ) -> tuple[str, str, datetime] | None:
        async with self.session_factory() as session:
            row = await session.scalar(
                select(UserRow).where(UserRow.username == username)
            )
            if row is None:
                return None
            row.role = role
            out = (row.username, row.role, row.created_at)
            await session.commit()
        return out

    async def delete_user(self, username: str) -> bool:
        async with self.session_factory() as session:
            result = await session.execute(
                delete(UserRow).where(UserRow.username == username)
            )
            await session.commit()
        return result.rowcount > 0

    async def count_admins(self) -> int:
        async with self.session_factory() as session:
            n = await session.scalar(
                select(func.count()).select_from(UserRow).where(UserRow.role == "admin")
            )
        return int(n or 0)
