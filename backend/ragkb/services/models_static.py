"""Каталог: одна модель из настроек."""
from __future__ import annotations

from ragkb.core.config import LLMConfig
from ragkb.services.models_labels import model_label
from ragkb.services.models_schemas import ModelInfo


class StaticCatalog:
    def __init__(self, cfg: LLMConfig):
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
