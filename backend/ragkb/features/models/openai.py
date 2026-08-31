"""Каталог моделей с OpenAI-совместимого GET /models."""
from __future__ import annotations

from typing import Any

from ragkb.core.config import LLMConfig
from ragkb.features.models.labels import model_label
from ragkb.features.models.schemas import ModelInfo
from ragkb.features.models.static import StaticCatalog


def listed_models(base_url: str, api_key: str = "") -> list[dict[str, Any]]:
    if not base_url:
        return []
    try:
        import httpx

        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        root = base_url.rstrip("/")
        with httpx.Client(timeout=2, headers=headers) as client:
            payload = client.get(f"{root}/models").json()
        out: list[dict[str, Any]] = []
        for entry in payload.get("data") or []:
            model_id = entry.get("id", "")
            if model_id:
                out.append({"id": model_id})
        return out
    except Exception:
        return []


class OpenAICatalog:
    def __init__(self, cfg: LLMConfig, installed: list[dict[str, Any]] | None = None):
        self.cfg = cfg
        self._installed = installed

    def list(self) -> list[ModelInfo]:
        allowed = {e.get("name", "") for e in self.cfg.available if e.get("name")}
        titles = {e.get("name", ""): e.get("title") for e in self.cfg.available}
        source = (
            self._installed
            if self._installed is not None
            else listed_models(self.cfg.base_url, self.cfg.api_key)
        )
        out: list[ModelInfo] = []
        for item in source:
            if allowed and item["id"] not in allowed:
                continue
            mid = item["id"]
            out.append(
                ModelInfo(
                    id=mid,
                    display_name=model_label(mid, titles.get(mid)),
                    is_default=mid == self.cfg.model,
                )
            )
        if not out:
            return StaticCatalog(self.cfg).list()
        if not any(item.is_default for item in out):
            out[0].is_default = True
        return out

    def resolve(self, requested: str | None) -> str:
        items = self.list()
        if not requested:
            for item in items:
                if item.is_default:
                    return item.id
            return self.cfg.model
        allowed = {item.id for item in items}
        if requested not in allowed:
            available = ", ".join(sorted(allowed)) if allowed else "ни одной"
            raise ValueError(
                f"Модель «{requested}» недоступна. Доступны: {available}"
            )
        return requested
