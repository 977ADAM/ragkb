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


def probe_ollama(base_url: str, names: list[str]) -> dict[str, dict[str, Any]]:
    """Спрашивает у Ollama, что она знает о моделях.

    Возвращает по имени модели словарь с полем context_window и признаком
    supports_tools. Отсутствие модели в ответе означает, что она не установлена.

    Никогда не поднимает исключений: список моделей не должен становиться
    недоступным из-за того, что недоступна Ollama. При отказе возвращается
    пустой словарь, и поля остаются незаполненными.
    """
    try:
        import httpx

        with httpx.Client(timeout=2) as client:
            tags = client.get(f"{base_url.rstrip('/')}/api/tags").json()
            installed = {m.get("name", "") for m in tags.get("models", [])}

            out: dict[str, dict[str, Any]] = {}
            for name in names:
                if name not in installed:
                    continue
                info: dict[str, Any] = {"supports_tools": False, "context_window": None}
                try:
                    shown = client.post(
                        f"{base_url.rstrip('/')}/api/show", json={"model": name}
                    ).json()
                except Exception:
                    out[name] = info
                    continue
                info["supports_tools"] = "tools" in (shown.get("capabilities") or [])
                # Ключ размера контекста несёт префикс архитектуры:
                # «qwen2.context_length», «llama.context_length» и так далее.
                for key, value in (shown.get("model_info") or {}).items():
                    if key.endswith(".context_length") and isinstance(value, int):
                        info["context_window"] = value
                        break
                out[name] = info
            return out
    except Exception:
        return {}


def available_models(cfg: LLMConfig, probe: bool = False) -> list[dict[str, Any]]:
    """Нормализованный список моделей для интерфейса.

    Пустой available означает, что переключения нет: отдаём одну текущую.

    При probe=True недостающие поля добираются из Ollama. Это не обязательно
    и не влияет на работоспособность: без неё модель просто описана скупее.
    """
    entries = cfg.available or [{"name": cfg.model}]
    out: list[dict[str, Any]] = []
    for entry in entries:
        model_id = entry.get("name", "")
        if not model_id:
            continue
        out.append({
            "id": model_id,
            "display_name": entry.get("title") or model_id,
            "context_window": None,
            "supports_tools": False,
            "is_default": model_id == cfg.model,
        })

    if probe and cfg.backend.lower() == "ollama":
        known = probe_ollama(cfg.base_url, [item["id"] for item in out])
        for item in out:
            extra = known.get(item["id"])
            if extra:
                item["context_window"] = extra["context_window"]
                item["supports_tools"] = extra["supports_tools"]

    return out


def resolve_model(cfg: LLMConfig, requested: str | None) -> str:
    """Проверяет запрошенное имя. Пустое означает «по умолчанию».

    Поднимает ValueError, если имя не разрешено — вызывающий код превращает
    это в отказ 400.
    """
    if not requested:
        return cfg.model
    allowed = {item["id"] for item in available_models(cfg)}
    if requested not in allowed:
        raise ValueError(
            f"Модель «{requested}» не разрешена. Доступны: {', '.join(sorted(allowed))}"
        )
    return requested
