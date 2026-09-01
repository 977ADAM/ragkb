from __future__ import annotations

import hashlib
import secrets
from datetime import timedelta

from sqlalchemy.exc import IntegrityError

from ragkb.features.auth.passwords import (
    SESSION_DAYS,
    hash_password,
    utcnow,
    verify_password,
)
from ragkb.features.auth.ports import AccountStore
from ragkb.platform.errors import Conflict, Unauthenticated


def _token_hash(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


class AuthService:
    def __init__(self, store: AccountStore) -> None:
        self._store = store

    async def _new_session(self, user_id: str) -> str:
        raw = secrets.token_urlsafe(32)
        expires_at = (utcnow() + timedelta(days=SESSION_DAYS)).isoformat()
        await self._store.create_session(user_id, _token_hash(raw), expires_at)
        return raw

    async def register(self, username: str, password: str) -> tuple[str, str]:
        try:
            user_id = await self._store.create_user(username, hash_password(password))
        except IntegrityError as exc:
            raise Conflict("Такой логин уже занят") from exc
        return username, await self._new_session(user_id)

    async def login(self, username: str, password: str) -> tuple[str, str]:
        row = await self._store.get_by_username(username)
        if row is None or not verify_password(password, row[2]):
            raise Unauthenticated("Неверный логин или пароль")
        user_id, canonical, _ = row
        return canonical, await self._new_session(user_id)

    async def logout(self, raw_token: str | None) -> None:
        if not raw_token:
            return
        await self._store.delete_session(_token_hash(raw_token))

    async def me(self, raw_token: str | None) -> str:
        if not raw_token:
            raise Unauthenticated("Не аутентифицирован")
        row = await self._store.user_for_token_hash(_token_hash(raw_token))
        if row is None:
            raise Unauthenticated("Не аутентифицирован")
        return row[1]
