"""Регистрация, вход, сессия. Пароль — Argon2, кука непрозрачная."""
from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

from ragkb.domain.ports import AccountStore
from ragkb.core.errors import Unauthenticated

COOKIE_NAME = "ragkb_session"
SESSION_DAYS = 7

_hasher = PasswordHasher()


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def hash_password(plain: str) -> str:
    return _hasher.hash(plain)


def verify_password(plain: str, password_hash: str) -> bool:
    try:
        return _hasher.verify(password_hash, plain)
    except (VerifyMismatchError, InvalidHashError):
        return False


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
        user_id = await self._store.create_user(
            username, hash_password(password), role="user"
        )
        return username, await self._new_session(user_id)

    async def login(self, username: str, password: str) -> tuple[str, str]:
        row = await self._store.get_by_username(username)
        if row is None or not verify_password(password, row[2]):
            raise Unauthenticated("Неверный логин или пароль")
        user_id, canonical, _password_hash, _role = row
        return canonical, await self._new_session(user_id)

    async def logout(self, raw_token: str | None) -> None:
        if not raw_token:
            return
        await self._store.delete_session(_token_hash(raw_token))

    async def me(self, raw_token: str | None) -> tuple[str, str]:
        if not raw_token:
            raise Unauthenticated("Не аутентифицирован")
        row = await self._store.user_for_token_hash(_token_hash(raw_token))
        if row is None:
            raise Unauthenticated("Не аутентифицирован")
        return row[1], row[2]
