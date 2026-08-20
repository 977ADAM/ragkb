"""Выбор генерирующей модели.

Имя модели приходит от клиента, поэтому проверяется по списку разрешённых:
передать его в Ollama как есть нельзя — незнакомое имя заставит её скачивать
модель, а это непредсказуемая задержка и заполнение диска по запросу извне.

Переключается только генерирующая модель. Эмбеддер заморожен индексом:
RAGPipeline._restore_embedder отказывается работать при расхождении, иначе
запрос и документы окажутся в разных векторных пространствах.
"""
from __future__ import annotations

from typing import Any

from .config import LLMConfig


def available_models(cfg: LLMConfig) -> list[dict[str, Any]]:
    """Нормализованный список моделей для интерфейса.

    Пустой available означает, что переключения нет: отдаём одну текущую.
    """
    entries = cfg.available or [{"name": cfg.model}]
    out: list[dict[str, Any]] = []
    for entry in entries:
        name = entry.get("name", "")
        if not name:
            continue
        out.append({
            "name": name,
            "title": entry.get("title") or name,
            "default": name == cfg.model,
        })
    return out


def resolve_model(cfg: LLMConfig, requested: str | None) -> str:
    """Проверяет запрошенное имя. Пустое означает «по умолчанию».

    Поднимает ValueError, если имя не разрешено — вызывающий код превращает
    это в отказ 400.
    """
    if not requested:
        return cfg.model
    allowed = {item["name"] for item in available_models(cfg)}
    if requested not in allowed:
        raise ValueError(
            f"Модель «{requested}» не разрешена. Доступны: {', '.join(sorted(allowed))}"
        )
    return requested
