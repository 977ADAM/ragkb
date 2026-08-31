"""Идентификация пользователя.

Аутентификацию ведёт внешний reverse proxy (на сервере — Angie); сюда
приходит готовый заголовок с логином.
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from fastapi import Request
from starlette.datastructures import Headers

from ragkb.core.config import AuthConfig
from ragkb.platform.errors import Forbidden, Unauthenticated

ANONYMOUS = "anonymous"


@dataclass(frozen=True)
class User:
    name: str
    email: str = ""
    groups: tuple[str, ...] = ()

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


def current_user(request: Request) -> User:
    cfg: AuthConfig = request.app.state.auth
    if cfg.mode == "disabled":
        return User(name=ANONYMOUS)
    user = user_from_headers(request.headers, cfg)
    if user is None:
        raise Unauthenticated("Не аутентифицирован")
    return user


def optional_user(request: Request) -> User | None:
    try:
        return current_user(request)
    except Unauthenticated:
        return None


def require_admin(request: Request) -> User:
    cfg: AuthConfig = request.app.state.auth
    user = current_user(request)
    if cfg.mode == "disabled":
        return user
    if not user.in_group(cfg.admin_group):
        raise Forbidden(f"Требуется членство в группе «{cfg.admin_group}»")
    return user
