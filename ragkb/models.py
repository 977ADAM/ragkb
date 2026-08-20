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


def installed_models(base_url: str) -> list[dict[str, Any]]:
    """Что Ollama держит установленным прямо сейчас.

    Возвращает список словарей с id, context_window и supports_tools.
    Никогда не поднимает исключений: недоступность Ollama означает, что
    генерирующих моделей нет, а не что сервис сломан.
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
                }
                try:
                    shown = client.post(f"{root}/api/show", json={"model": model_id}).json()
                except Exception:
                    out.append(info)
                    continue
                info["supports_tools"] = "tools" in (shown.get("capabilities") or [])
                # Ключ размера контекста несёт префикс архитектуры:
                # «qwen2.context_length», «llama.context_length» и так далее.
                for key, value in (shown.get("model_info") or {}).items():
                    if key.endswith(".context_length") and isinstance(value, int):
                        info["context_window"] = value
                        break
                out.append(info)
            return out
    except Exception:
        return []


def available_models(
    cfg: LLMConfig, installed: list[dict[str, Any]] | None = None
) -> list[dict[str, Any]]:
    """Модели, которые можно выбрать прямо сейчас.

    Источник истины — сама Ollama: что установлено, то и предлагаем.
    Список в конфигурации ничего не задаёт, а только сужает: пустой
    означает «всё установленное», заполненный — подмножество.

    Пустой результат означает, что генерирующих моделей нет и сервис
    работает в режиме поиска — отвечает найденными фрагментами.

    Для бэкендов, кроме ollama, перечислить установленное неоткуда:
    отдаём одну модель из настроек.

    Параметр installed — точка подмены для тестов: он избавляет их
    от зависимости от запущенной Ollama.
    """
    if cfg.backend.lower() != "ollama":
        return [{
            "id": cfg.model,
            "display_name": cfg.model,
            "context_window": None,
            "supports_tools": False,
            "is_default": True,
        }]

    allowed = {entry.get("name", "") for entry in cfg.available if entry.get("name")}
    titles = {entry.get("name", ""): entry.get("title") for entry in cfg.available}

    out: list[dict[str, Any]] = []
    source = installed if installed is not None else installed_models(cfg.base_url)
    for item in source:
        if allowed and item["id"] not in allowed:
            continue
        out.append({
            "id": item["id"],
            "display_name": titles.get(item["id"]) or item["id"],
            "context_window": item["context_window"],
            "supports_tools": item["supports_tools"],
            "is_default": item["id"] == cfg.model,
        })

    # Модель из настроек может быть не установлена — тогда по умолчанию
    # выбирается первая доступная, иначе интерфейс не подсветит ничего.
    if out and not any(item["is_default"] for item in out):
        out[0]["is_default"] = True
    return out


def resolve_model(
    cfg: LLMConfig, requested: str | None,
    installed: list[dict[str, Any]] | None = None
) -> str:
    """Проверяет запрошенное имя по тому, что установлено прямо сейчас.

    Пустое означает «по умолчанию»: берётся модель из настроек, а если
    её нет среди установленных — первая доступная. Когда моделей нет
    вовсе, возвращается модель из настроек: пайплайн не достучится до неё
    и соберёт ответ экстрактивно, то есть сервис перейдёт в режим поиска.

    Поднимает ValueError на имя, которого нет среди установленных —
    вызывающий превращает это в отказ 400. Скачать неизвестную модель
    таким образом нельзя: её просто нет в списке.
    """
    items = available_models(cfg, installed)
    if not requested:
        for item in items:
            if item["is_default"]:
                return str(item["id"])
        return cfg.model

    allowed = {item["id"] for item in items}
    if requested not in allowed:
        available = ", ".join(sorted(allowed)) if allowed else "ни одной"
        raise ValueError(
            f"Модель «{requested}» недоступна. Установлены: {available}"
        )
    return requested
