"""Правила списка пользователей, смены роли и удаления."""
from __future__ import annotations

from datetime import datetime

from ragkb.core.errors import Forbidden, InvalidRequest, NotFound
from ragkb.domain.ports import AccountStore
from ragkb.services.auth import hash_password

_ROLES = frozenset({"user", "admin"})


def _user_payload(username: str, role: str, created_at: datetime) -> dict[str, str]:
    return {
        "username": username,
        "role": role,
        "created_at": created_at.isoformat(),
    }


class AdminUsersService:
    def __init__(self, store: AccountStore) -> None:
        self._store = store

    async def list(self) -> list[dict[str, str]]:
        rows = await self._store.list_users()
        return [_user_payload(name, role, created) for name, role, created in rows]

    async def create(self, username: str, password: str, role: str) -> dict[str, str]:
        if role not in _ROLES:
            raise InvalidRequest("роль только user или admin")
        await self._store.create_user(username, hash_password(password), role=role)
        profile = await self._store.get_profile(username)
        if profile is None:
            raise NotFound("Пользователь не найден")
        new_role, created_at = profile
        return _user_payload(username, new_role, created_at)

    async def set_role(self, username: str, role: str) -> dict[str, str]:
        if role not in _ROLES:
            raise InvalidRequest("роль только user или admin")
        row = await self._store.get_by_username(username)
        if row is None:
            raise NotFound("Пользователь не найден")
        _uid, canonical, _hash, current_role = row
        if current_role == "admin" and role == "user" and await self._store.count_admins() <= 1:
            raise Forbidden("нельзя разжаловать последнего админа")
        updated = await self._store.set_role(canonical, role)
        if updated is None:
            raise NotFound("Пользователь не найден")
        name, new_role, created_at = updated
        return _user_payload(name, new_role, created_at)

    async def delete(self, username: str, actor: str) -> None:
        if username == actor:
            raise Forbidden("нельзя удалить себя")
        row = await self._store.get_by_username(username)
        if row is None:
            raise NotFound("Пользователь не найден")
        if row[3] == "admin" and await self._store.count_admins() <= 1:
            raise Forbidden("нельзя разжаловать последнего админа")
        deleted = await self._store.delete_user(username)
        if not deleted:
            raise NotFound("Пользователь не найден")
