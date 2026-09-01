from __future__ import annotations

import hashlib
import secrets
import sqlite3
from datetime import timedelta

from ragkb.features.auth.passwords import hash_password, verify_password
from ragkb.features.auth.ports import AccountStore
from ragkb.features.auth.sqlite import SESSION_DAYS, utcnow
from ragkb.platform.errors import Conflict, Unauthenticated


def _token_hash(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


class AuthService:
    def __init__(self, store: AccountStore) -> None:
        self._store = store

    def _new_session(self, user_id: str) -> str:
        raw = secrets.token_urlsafe(32)
        expires_at = (utcnow() + timedelta(days=SESSION_DAYS)).isoformat()
        self._store.create_session(user_id, _token_hash(raw), expires_at)
        return raw

    def register(self, username: str, password: str) -> tuple[str, str]:
        try:
            user_id = self._store.create_user(username, hash_password(password))
        except sqlite3.IntegrityError as exc:
            raise Conflict("Такой логин уже занят") from exc
        return username, self._new_session(user_id)

    def login(self, username: str, password: str) -> tuple[str, str]:
        row = self._store.get_by_username(username)
        if row is None or not verify_password(password, row[2]):
            raise Unauthenticated("Неверный логин или пароль")
        user_id, canonical, _ = row
        return canonical, self._new_session(user_id)

    def logout(self, raw_token: str | None) -> None:
        if not raw_token:
            return
        self._store.delete_session(_token_hash(raw_token))

    def me(self, raw_token: str | None) -> str:
        if not raw_token:
            raise Unauthenticated("Не аутентифицирован")
        row = self._store.user_for_token_hash(_token_hash(raw_token))
        if row is None:
            raise Unauthenticated("Не аутентифицирован")
        return row[1]
