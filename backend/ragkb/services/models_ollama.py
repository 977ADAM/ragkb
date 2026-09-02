"""Каталог установленных моделей Ollama."""
from __future__ import annotations

from typing import Any

from ragkb.core.config import LLMConfig
from ragkb.services.models_labels import model_label
from ragkb.services.models_schemas import ModelInfo


def installed_models(base_url: str) -> list[dict[str, Any]]:
    try:
        import httpx

        root = base_url.rstrip("/")
        with httpx.Client(timeout=2) as client:
            tags = client.get(f"{root}/api/tags").json()
            out: list[dict[str, Any]] = []
            for entry in tags.get("models", []):
                model_id = entry.get("name", "")
                if not model_id:
                    continue
                info: dict[str, Any] = {
                    "id": model_id,
                    "context_window": None,
                    "supports_tools": False,
                }
                try:
                    shown = client.post(
                        f"{root}/api/show", json={"model": model_id}
                    ).json()
                except Exception:
                    out.append(info)
                    continue
                info["supports_tools"] = "tools" in (shown.get("capabilities") or [])
                for key, value in (shown.get("model_info") or {}).items():
                    if key.endswith(".context_length") and isinstance(value, int):
                        info["context_window"] = value
                        break
                out.append(info)
            return out
    except Exception:
        return []


class OllamaCatalog:
    def __init__(self, cfg: LLMConfig, installed: list[dict[str, Any]] | None = None):
        self.cfg = cfg
        self._installed = installed

    def list(self) -> list[ModelInfo]:
        allowed = {e.get("name", "") for e in self.cfg.available if e.get("name")}
        titles = {e.get("name", ""): e.get("title") for e in self.cfg.available}
        source = (
            self._installed
            if self._installed is not None
            else installed_models(self.cfg.base_url)
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
                    context_window=item["context_window"],
                    supports_tools=item["supports_tools"],
                    is_default=mid == self.cfg.model,
                )
            )
        if out and not any(item.is_default for item in out):
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
                f"Модель «{requested}» недоступна. Установлены: {available}"
            )
        return requested
