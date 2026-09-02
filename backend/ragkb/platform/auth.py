"""Идентификация пользователя.

В режиме proxy аутентификацию ведёт reverse proxy (на сервере — Angie).
В режиме session личность берётся только из куки, не из заголовков.
"""
from __future__ import annotations

import hashlib
from collections.abc import Iterable
from dataclasses import dataclass

from fastapi import Request
from starlette.datastructures import Headers

from ragkb.core.config import AuthConfig
from ragkb.platform.errors import Forbidden, Unauthenticated
from ragkb.services.auth import COOKIE_NAME

ANONYMOUS = "anonymous"


@dataclass(frozen=True)
class User:
    name: str
    email: str = ""
    groups: tuple[str, ...] = ()
    role: str = "user"

    def in_group(self, group: str) -> bool:
        return group in self.groups


def parse_groups(values: Iterable[str]) -> tuple[str, ...]:
    groups: list[str] = []
    for value in values:
        for part in value.split(","):
            part = part.strip()
            if part and part not in groups:
                groups.append(part)
    return tuple(groups)


def user_from_headers(headers: Headers, cfg: AuthConfig) -> User | None:
    name = (headers.get(cfg.header) or "").strip()
    if not name:
        return None
    return User(
        name=name,
        email=(headers.get(cfg.email_header) or "").strip(),
        groups=parse_groups(headers.getlist(cfg.groups_header)),
    )


async def current_user(request: Request) -> User:
    cfg: AuthConfig = request.app.state.auth
    if cfg.mode == "disabled":
        return User(name=ANONYMOUS)
    if cfg.mode == "session":
        raw = request.cookies.get(COOKIE_NAME)
        if not raw:
            raise Unauthenticated("Не аутентифицирован")
        digest = hashlib.sha256(raw.encode()).hexdigest()
        accounts = request.app.state.container.accounts
        if accounts is None:
            request.app.state.container._ensure_postgres()
            accounts = request.app.state.container.accounts
        if accounts is None:
            raise Unauthenticated("Не аутентифицирован")
        row = await accounts.user_for_token_hash(digest)
        if row is None:
            raise Unauthenticated("Не аутентифицирован")
        return User(name=row[1], role=row[2])
    user = user_from_headers(request.headers, cfg)
    if user is None:
        raise Unauthenticated("Не аутентифицирован")
    return user


async def optional_user(request: Request) -> User | None:
    try:
        return await current_user(request)
    except Unauthenticated:
        return None


async def require_admin(request: Request) -> User:
    cfg: AuthConfig = request.app.state.auth
    user = await current_user(request)
    if cfg.mode == "disabled":
        return user
    if cfg.mode == "session":
        if user.role != "admin":
            raise Forbidden("Требуется роль администратора")
        return user
    if not user.in_group(cfg.admin_group):
        raise Forbidden(f"Требуется членство в группе «{cfg.admin_group}»")
    return user
