"""Идентификация пользователя.

Аутентификацию ведёт oauth2-proxy перед сервисом; сюда приходит уже готовый
заголовок с логином. Весь остальной код знает только про User — если однажды
прокси сменится на другой механизм, правится только этот модуль.
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from fastapi import HTTPException, Request
from starlette.datastructures import Headers

from .config import AuthConfig

# Имя пользователя, под которым работает сервис при выключенной аутентификации.
ANONYMOUS = "anonymous"


@dataclass(frozen=True)
class User:
    name: str
    email: str = ""
    groups: tuple[str, ...] = ()

    def in_group(self, group: str) -> bool:
        return group in self.groups


def parse_groups(values: Iterable[str]) -> tuple[str, ...]:
    """Разбирает группы из заголовков.

    Несколько групп приходят либо повторяющимися заголовками, либо одной
    строкой через запятую — формат зависит от настройки прокси. Разбираем оба
    случая, иначе проверка административной группы окажется ненадёжной.
    Порядок сохраняем, повторы отбрасываем.
    """
    groups: list[str] = []
    for value in values:
        for part in value.split(","):
            part = part.strip()
            if part and part not in groups:
                groups.append(part)
    return tuple(groups)


def user_from_headers(headers: Headers, cfg: AuthConfig) -> User | None:
    """Собирает User из заголовков. None — пользователь не установлен."""
    name = (headers.get(cfg.header) or "").strip()
    if not name:
        return None
    return User(
        name=name,
        email=(headers.get(cfg.email_header) or "").strip(),
        groups=parse_groups(headers.getlist(cfg.groups_header)),
    )


def current_user(request: Request) -> User:
    """Зависимость FastAPI: кто выполняет запрос. 401, если неизвестно."""
    cfg: AuthConfig = request.app.state.auth
    if cfg.mode == "disabled":
        return User(name=ANONYMOUS)
    user = user_from_headers(request.headers, cfg)
    if user is None:
        raise HTTPException(status_code=401, detail="Не аутентифицирован")
    return user


def optional_user(request: Request) -> User | None:
    """То же, но без исключения — для эндпоинтов, открытых без аутентификации."""
    try:
        return current_user(request)
    except HTTPException:
        return None


def require_admin(request: Request) -> User:
    """Зависимость для административных операций."""
    cfg: AuthConfig = request.app.state.auth
    user = current_user(request)
    if cfg.mode == "disabled":
        return user
    if not user.in_group(cfg.admin_group):
        raise HTTPException(
            status_code=403,
            detail=f"Требуется членство в группе «{cfg.admin_group}»",
        )
    return user
