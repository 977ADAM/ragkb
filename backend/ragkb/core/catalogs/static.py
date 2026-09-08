"""Каталог: одна модель из настроек."""
from __future__ import annotations

from ragkb.core.catalogs.info import ModelInfo
from ragkb.core.catalogs.labels import model_label
from ragkb.core.config import Settings


class StaticCatalog:
    def __init__(self, cfg: Settings.LLMConfig):
        self.cfg = cfg

    def list(self) -> list[ModelInfo]:
        mid = self.cfg.model
        return [ModelInfo(id=mid, display_name=model_label(mid), is_default=True)]

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
