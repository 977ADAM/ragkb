"""Чат-модель LangChain: OpenAI-совместимый HTTP.

Генерация идёт через `langchain-openai`, поэтому подходит любой сервер с
совместимым API: vLLM, llama.cpp, LM Studio, ollama (её корень с `/v1`).
Собственного HTTP-клиента у сервиса больше нет; отказы переводим в доменную
ошибку, чтобы администратор видел действие, а не исключение пакета.
"""
from __future__ import annotations

from langchain_core.language_models import BaseChatModel
from pydantic import SecretStr

from .config import Settings
from .errors import EngineUnavailable


def build_chat_model(cfg: Settings.LLMConfig, model: str | None = None) -> BaseChatModel:
    """Модель для конкретного запроса (в интерфейсе можно выбрать другую)."""
    from langchain_openai import ChatOpenAI

    if not cfg.base_url:
        raise EngineUnavailable(
            "Не задан адрес генерации: укажите llm.base_url (RAGKB_LLM_URL) — "
            "корень OpenAI-совместимого API, обычно с /v1"
        )
    name = model or cfg.model
    if not name:
        raise EngineUnavailable(
            "Не выбрана модель генерации: задайте llm.model (RAGKB_LLM_MODEL) "
            "или выберите модель в интерфейсе"
        )
    return ChatOpenAI(
        model=name,
        base_url=cfg.base_url.rstrip("/"),
        # Ollama и большинство локальных серверов ключ не проверяют, но
        # клиент требует непустое значение.
        api_key=SecretStr(cfg.api_key or "not-needed"),
        temperature=cfg.temperature,
        max_completion_tokens=cfg.max_tokens,
        timeout=cfg.timeout,
    )


def chat_model_name(cfg: Settings.LLMConfig, model: str | None = None) -> str:
    return f"openai:{model or cfg.model}"
