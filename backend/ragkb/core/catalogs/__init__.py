"""Адаптеры каталога моделей: OpenAI-совместимый HTTP, Ollama, статический список."""
from __future__ import annotations

from ragkb.core.catalogs.ollama import OllamaCatalog
from ragkb.core.catalogs.openai import OpenAICatalog
from ragkb.core.catalogs.static import StaticCatalog
from ragkb.core.config import Settings


def make_catalog(llm: Settings.LLMConfig):
    kind = llm.backend.lower()
    if kind in {"openai", "vllm", "openai-compatible"}:
        return OpenAICatalog(llm)
    if kind == "ollama":
        return OllamaCatalog(llm)
    return StaticCatalog(llm)
