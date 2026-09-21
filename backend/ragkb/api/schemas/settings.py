"""Схемы страницы настроек."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class SettingsUpdate(BaseModel):
    """Правка настроек: значения по путям и пути, которые надо сбросить.

    Путь — «раздел.поле» (`retrieval.top_k`) или имя верхнеуровневого поля.
    Сброс убирает переопределение: поле возвращается к значению окружения.
    """

    values: dict[str, Any] = Field(default_factory=dict)
    reset: list[str] = Field(default_factory=list)
