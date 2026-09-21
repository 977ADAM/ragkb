"""Каталог установленных моделей Ollama."""
from __future__ import annotations

from typing import Any

from ragkb.core.catalogs.info import ModelInfo
from ragkb.core.catalogs.labels import model_label
from ragkb.core.config import Settings


def installed_models(base_url: str) -> list[dict[str, Any]]:
    """Что установлено в Ollama: возможности, контекст и длина вектора.

    `/api/show` отдаёт `capabilities` (completion, tools, embedding, vision) и
    `model_info`. По ним каталог решает, годится модель для генерации или для
    эмбеддингов, — это надёжнее, чем угадывать по имени.
    """
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
                    "capabilities": [],
                    "embedding_dim": None,
                }
                try:
                    shown = client.post(
                        f"{root}/api/show", json={"model": model_id}
                    ).json()
                except Exception:
                    out.append(info)
                    continue
                _apply_show(info, shown)
                out.append(info)
            return out
    except Exception:
        return []


def _apply_show(info: dict[str, Any], shown: dict[str, Any]) -> None:
    capabilities = [str(item) for item in (shown.get("capabilities") or [])]
    info["capabilities"] = capabilities
    info["supports_tools"] = "tools" in capabilities
    for key, value in (shown.get("model_info") or {}).items():
        if not isinstance(value, int):
            continue
        if key.endswith(".context_length") and info["context_window"] is None:
            info["context_window"] = value
        elif key.endswith("embedding_length") and info["embedding_dim"] is None:
            info["embedding_dim"] = value


def embedding_options(installed: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Модели, которыми можно считать эмбеддинги.

    Признак — возможность `embedding` из /api/show. Если Ollama о возможностях
    не сообщает вовсе (старые версии), показываем всё установленное: выбрать
    неподходящую модель всё равно не даст проверка при индексации, а пустой
    список был бы хуже.
    """
    known = [item for item in installed if item.get("capabilities")]
    source = known or installed
    return [
        {
            "id": item["id"],
            "dim": item.get("embedding_dim"),
            "label": _embedding_label(item),
        }
        for item in source
        if not known or "embedding" in item.get("capabilities", [])
    ]


def _embedding_label(item: dict[str, Any]) -> str:
    dim = item.get("embedding_dim")
    size = item.get("size")
    parts: list[str] = []
    if isinstance(dim, int) and dim > 0:
        parts.append(f"{dim} координат")
    if isinstance(size, int) and size > 0:
        parts.append(f"{size / 1e9:.2f} ГБ")
    return ", ".join(parts)


class OllamaCatalog:
    def __init__(self, cfg: Settings.LLMConfig, installed: list[dict[str, Any]] | None = None):
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
