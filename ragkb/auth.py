"""Идентификация пользователя.

Аутентификацию ведёт oauth2-proxy перед сервисом; сюда приходит уже готовый
заголовок с логином. Весь остальной код знает только про User — если однажды
прокси сменится на другой механизм, правится только этот модуль.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

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
