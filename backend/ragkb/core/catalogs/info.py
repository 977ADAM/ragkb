"""Описание модели для каталога. Без HTTP и провайдера."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ModelInfo:
    id: str
    display_name: str | None = None
    context_window: int | None = None
    supports_tools: bool = False
    is_default: bool = False
