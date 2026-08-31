"""Каталог: одна модель из настроек."""
from __future__ import annotations

from ragkb.core.config import LLMConfig
from ragkb.features.models.schemas import ModelInfo


class StaticCatalog:
    def __init__(self, cfg: LLMConfig):
        self.cfg = cfg

    def list(self) -> list[ModelInfo]:
        return [ModelInfo(id=self.cfg.model, display_name=self.cfg.model, is_default=True)]

    def resolve(self, requested: str | None) -> str:
        items = self.list()
        if not requested:
            return items[0].id
        allowed = {item.id for item in items}
        if requested not in allowed:
            raise ValueError(
                f"Модель «{requested}» недоступна. Установлены: {items[0].id}"
            )
        return requested
