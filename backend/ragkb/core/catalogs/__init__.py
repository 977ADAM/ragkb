"""Адаптеры каталога моделей: OpenAI-совместимый HTTP, Ollama, статический список."""
from __future__ import annotations

from typing import Any

from ragkb.core.catalogs.ollama import OllamaCatalog, embedding_options, installed_models
from ragkb.core.catalogs.openai import OpenAICatalog, listed_models
from ragkb.core.catalogs.static import StaticCatalog
from ragkb.core.config import Settings


def make_catalog(llm: Settings.LLMConfig):
    kind = llm.backend.lower()
    if kind in {"openai", "vllm", "openai-compatible"}:
        return OpenAICatalog(llm)
    if kind == "ollama":
        return OllamaCatalog(llm)
    return StaticCatalog(llm)


def embedding_models(cfg: Settings) -> list[dict[str, Any]]:
    """Модели, доступные для индексации, — как список моделей для генерации.

    Источник зависит от бэкенда: у Ollama — её `/api/tags` (показываем только
    то, что установлено и умеет эмбеддинги), у openai — `GET {base_url}/models`
    OpenAI-совместимого сервера. Бэкенд `fake` (тестовый) моделей не имеет:
    он даёт детерминированные векторы независимо от имени.
    """
    kind = cfg.embedding.backend.lower()
    if kind in {"fake", "test"}:
        return []
    if not cfg.embedding.base_url:
        return []
    if kind in {"openai", "http", "openai-compatible"}:
        return listed_models(cfg.embedding.base_url, cfg.embedding.api_key)
    return embedding_options(installed_models(cfg.embedding.base_url))
