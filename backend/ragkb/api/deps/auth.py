"""HTTP-идентификация и Depends-фабрики auth.

В режиме proxy личность ведёт reverse proxy (на сервере — Angie).
В режиме session личность берётся только из куки, не из заголовков.
"""
from __future__ import annotations

import hashlib
from collections.abc import Iterable
from typing import Annotated

from fastapi import Depends, Request, Response
from starlette.datastructures import Headers

from ragkb.container import Container
from ragkb.core.config import AuthConfig
from ragkb.core.errors import Forbidden, Unauthenticated
from ragkb.domain.entities import ANONYMOUS, User
from ragkb.services.auth import COOKIE_NAME, SESSION_DAYS, AuthService


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
        container: Container = request.app.state.container
        accounts = container.accounts
        if accounts is None:
            container._ensure_postgres()
            accounts = container.accounts
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


def get_auth_service(request: Request) -> AuthService:
    c: Container = request.app.state.container
    c._ensure_postgres()
    if c.accounts is None:
        raise RuntimeError("Хранилище учёток недоступно: Postgres не подключён")
    return AuthService(c.accounts)


AuthSvc = Annotated[AuthService, Depends(get_auth_service)]


def cookie_secure(request: Request) -> bool:
    forwarded = request.headers.get("x-forwarded-proto", "").split(",")[0].strip()
    return request.url.scheme == "https" or forwarded == "https"


def set_session_cookie(response: Response, request: Request, token: str) -> None:
    response.set_cookie(
        COOKIE_NAME,
        token,
        httponly=True,
        secure=cookie_secure(request),
        samesite="lax",
        path="/",
        max_age=SESSION_DAYS * 24 * 60 * 60,
    )


def clear_session_cookie(response: Response, request: Request) -> None:
    response.delete_cookie(
        COOKIE_NAME,
        path="/",
        httponly=True,
        samesite="lax",
        secure=cookie_secure(request),
    )


def raw_cookie(request: Request) -> str | None:
    return request.cookies.get(COOKIE_NAME)
