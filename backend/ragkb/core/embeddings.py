"""Эмбеддинги LangChain: Ollama для работы, детерминированный fake для тестов.

Тонкий слой над `langchain-ollama`: наша задача — собрать объект `Embeddings`
из конфигурации и перевести отказы (Ollama не поднята, модель не загружена)
в доменную ошибку с понятным действием. Сами запросы, пакетирование и повторы
делает интеграционный пакет LangChain.
"""
from __future__ import annotations

from typing import Any

from langchain_core.embeddings import DeterministicFakeEmbedding, Embeddings

from .config import Settings
from .errors import EngineUnavailable


def build_embeddings(cfg: Settings.EmbeddingConfig) -> Embeddings:
    """Эмбеддер по конфигурации: ollama | fake."""
    backend = cfg.backend.lower()
    if backend == "ollama":
        return _ollama(cfg)
    if backend in {"fake", "test"}:
        return DeterministicFakeEmbedding(size=cfg.fake_dim)
    raise EngineUnavailable(
        f"Неизвестный бэкенд эмбеддингов «{cfg.backend}»: доступны ollama и fake"
    )


def embedder_name(cfg: Settings.EmbeddingConfig) -> str:
    """Имя эмбеддера для манифеста и /status: смена модели ломает старый индекс."""
    if cfg.backend.lower() in {"fake", "test"}:
        return f"fake:{cfg.fake_dim}"
    return f"{cfg.backend.lower()}:{cfg.model}"


def _ollama(cfg: Settings.EmbeddingConfig) -> Embeddings:
    from langchain_ollama import OllamaEmbeddings

    if not cfg.base_url:
        raise EngineUnavailable(
            "Не задан адрес Ollama: укажите embedding.base_url "
            "(RAGKB_EMBEDDING_URL), например http://127.0.0.1:11434"
        )
    try:
        return OllamaEmbeddings(
            model=cfg.model,
            base_url=cfg.base_url.rstrip("/"),
            keep_alive=keep_alive_seconds(cfg.keep_alive),
            num_ctx=cfg.num_ctx or None,
            # Проверка модели на сборке объекта: неоттянутая модель — самая
            # частая причина отказа, и узнать о ней лучше до чтения корпуса.
            validate_model_on_init=cfg.validate_model,
            client_kwargs={"timeout": cfg.timeout},
        )
    except Exception as exc:
        raise EngineUnavailable(explain_embedding_error(exc, cfg)) from exc


def explain_embedding_error(exc: Exception, cfg: Settings.EmbeddingConfig) -> str:
    """Переводит отказ эмбеддера в текст, по которому можно действовать.

    LangChain и клиент Ollama отдают исходные сообщения сервера; здесь они
    превращаются в «что сделать», иначе администратор видит исключение
    интеграционного пакета.
    """
    text = str(exc)
    lowered = text.lower()
    address = cfg.base_url or "адрес не задан"
    if "not found" in lowered or "no such model" in lowered or "pull" in lowered:
        return (
            f"Модель эмбеддингов «{cfg.model}» не установлена в Ollama "
            f"({address}). Установите: ollama pull {cfg.model}"
        )
    if any(
        marker in lowered
        for marker in ("connect", "refused", "timed out", "timeout", "unreachable")
    ):
        return (
            f"Ollama недоступна по адресу {address} ({type(exc).__name__}). "
            f"Запустите `ollama serve` или укажите её адрес в RAGKB_EMBEDDING_URL"
        )
    return f"Эмбеддинги «{embedder_name(cfg)}» недоступны: {text}"


def keep_alive_seconds(value: str | int | None) -> int | None:
    """«30m» → 1800: langchain-ollama принимает длительность числом секунд.

    В конфиге и .env удобнее писать с единицей измерения, а в клиент Ollama
    уходит число. Непонятное значение игнорируем — пусть решает Ollama,
    а не падает старт сервиса.
    """
    if value is None or value == "":
        return None
    if isinstance(value, int):
        return value
    text = str(value).strip().lower()
    if text.isdigit():
        return int(text)
    units = {"s": 1, "m": 60, "h": 3600}
    suffix = text[-1:]
    if suffix in units and text[:-1].isdigit():
        return int(text[:-1]) * units[suffix]
    return None


def embedding_dim(embeddings: Embeddings) -> int | None:
    """Длина вектора, если бэкенд умеет назвать её без запроса."""
    for attr in ("dimensions", "size"):
        value = getattr(embeddings, attr, None)
        if isinstance(value, int) and value > 0:
            return value
    return None


def embed_probe(embeddings: Embeddings) -> dict[str, Any]:
    """Дешёвая проба: бэкенд отвечает и какой длины вектор отдаёт."""
    return {"ok": True, "dim": len(embeddings.embed_query("проверка"))}
