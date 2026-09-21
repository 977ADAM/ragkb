from __future__ import annotations

import os
from pathlib import Path
from typing import Any, ClassVar
from urllib.parse import quote_plus

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Корень репозитория: backend/ragkb/core/config.py → backend/ragkb/core → … .
# Нужен, чтобы .env находился независимо от текущего каталога процесса:
# при запуске из backend/ (make migrate, alembic) путь «.env» указывал бы
# на несуществующий backend/.env.
_PROJECT_ROOT = Path(__file__).resolve().parents[3]


def env_files() -> tuple[str, ...]:
    """Файлы окружения: ENV_FILE, иначе .env в корне репозитория.

    Значения из окружения процесса всё равно сильнее файла, поэтому в
    контейнере (где корня репозитория нет) ничего не ломается.
    """
    explicit = os.environ.get("ENV_FILE")
    if explicit:
        return (explicit,)
    return (str(_PROJECT_ROOT / ".env"),)


class Settings(BaseSettings):
    class ChunkConfig(BaseModel):
        # Границы чанка задаёт RecursiveCharacterTextSplitter (langchain):
        # разделители — абзац, конец предложения, строка, пробел.
        size: int = 900
        overlap: int = 150

    class EmbeddingConfig(BaseModel):
        # ollama — рабочий путь (langchain-ollama): модель живёт вне процесса
        # сервиса, поэтому в образе нет ни torch, ни весов эмбеддера.
        # fake — детерминированные векторы без сети: тесты и офлайн-прогоны.
        backend: str = "ollama"
        model: str = "qwen3-embedding:0.6b"
        # Адрес Ollama — корень API, без /v1.
        base_url: str = "http://127.0.0.1:11434"
        # Первый запрос поднимает модель в память Ollama: на холодную это
        # заметно дольше одного запроса, поэтому таймаут щедрый.
        timeout: int = 300
        # Сколько держать модель загруженной после индексации: следующий
        # вопрос не должен ждать повторной загрузки весов.
        keep_alive: str = "30m"
        # 0 — не переопределять контекст модели.
        num_ctx: int = 0
        # langchain-ollama проверяет наличие модели при сборке объекта.
        validate_model: bool = True
        # Размерность вектора у бэкенда fake.
        fake_dim: int = 1024

    class StoreConfig(BaseModel):
        # chroma — рабочий бэкенд (langchain-chroma, персистентный клиент).
        # memory — InMemoryVectorStore из langchain-core: тесты без диска.
        backend: str = "chroma"
        collection: str = "knowledge_base"
        chroma_host: str = ""
        chroma_port: int = 8000
        hnsw_construction_ef: int = 200
        hnsw_search_ef: int = 100
        hnsw_m: int = 16

    class RetrievalConfig(BaseModel):
        top_k: int = 5
        candidates: int = 30
        use_bm25: bool = True
        use_dense: bool = True
        # Веса источников в слиянии RRF. Единица у обоих — прежнее поведение:
        # вклад лексического и плотного поиска равный.
        bm25_weight: float = 1.0
        dense_weight: float = 1.0
        rrf_k: int = 60
        use_mmr: bool = True
        mmr_lambda: float = 0.7
        # Порог по близости плотного поиска: ниже него система честно отвечает
        # «не найдено», а не отдаёт случайные абзацы.
        min_score: float = 0.0
        reranker: str = "none"          # none | http
        reranker_model: str = "BAAI/bge-reranker-v2-m3"
        # Адрес реранкера по HTTP: корень OpenAI-совместимого API (…/v1) или
        # полный адрес до /rerank. Пустой адрес при reranker: http — ошибка
        # настройки, о ней пишем в лог, а не молчим.
        reranker_url: str = ""
        reranker_api_key: str = ""
        reranker_timeout: int = 60
        # Порог по оценке реранкера: шкала у каждой модели своя, поэтому по
        # умолчанию выключен — включать только после замера на своём наборе.
        min_rerank_score: float = 0.0

    class LLMConfig(BaseModel):
        # Генерация — OpenAI-совместимый HTTP (langchain-openai): vLLM,
        # llama.cpp, LM Studio, Ollama (её корень с /v1). Поле backend
        # выбирает только источник каталога моделей: openai | ollama | static.
        backend: str = "openai"
        model: str = ""
        base_url: str = ""
        api_key: str = ""
        temperature: float = 0.1
        max_tokens: int = 256
        timeout: int = 600
        available: list[dict[str, str]] = []

    class OrganizationConfig(BaseModel):
        name: str = ""
        id: str = ""
        description: str = ""

    class LoggingConfig(BaseModel):
        level: str = "INFO"
        dir: str = "data/logs"

    model_config: ClassVar[SettingsConfigDict] = SettingsConfigDict(
        env_file=env_files(),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    docs_dir: str = "data/docs"
    index_dir: str = "data/index"
    # Переопределения со страницы настроек: накладываются поверх окружения
    # при старте, чтобы правка из интерфейса переживала перезапуск.
    settings_file: str = "data/settings.json"
    chunking: ChunkConfig = ChunkConfig()
    embedding: EmbeddingConfig = EmbeddingConfig()
    store: StoreConfig = StoreConfig()
    retrieval: RetrievalConfig = RetrievalConfig()
    llm: LLMConfig = LLMConfig()
    organization: OrganizationConfig = OrganizationConfig()
    logging: LoggingConfig = LoggingConfig()

    # Прямой URL базы (RAGKB_DATABASE_URL) сильнее сборки из POSTGRES_*:
    # он же приходит из .env и из переменных окружения.
    database_url_override: str = Field(default="", validation_alias="RAGKB_DATABASE_URL")
    postgresql_password: str = Field(default="", validation_alias="POSTGRES_PASSWORD")
    postgresql_user: str = Field(default="", validation_alias="POSTGRES_USER")
    postgresql_db: str = Field(default="", validation_alias="POSTGRES_DB")
    postgresql_host: str = Field(default="postgres", validation_alias="POSTGRES_HOST")

    _ENV: ClassVar[dict[str, tuple[str | None, str]]] = {
        "RAGKB_DOCS_DIR": (None, "docs_dir"),
        "RAGKB_INDEX_DIR": (None, "index_dir"),
        "RAGKB_SETTINGS_FILE": (None, "settings_file"),
        "RAGKB_EMBEDDING_BACKEND": ("embedding", "backend"),
        "RAGKB_EMBEDDING_MODEL": ("embedding", "model"),
        "RAGKB_EMBEDDING_URL": ("embedding", "base_url"),
        "RAGKB_EMBEDDING_TIMEOUT": ("embedding", "timeout"),
        "RAGKB_EMBEDDING_KEEP_ALIVE": ("embedding", "keep_alive"),
        "RAGKB_EMBEDDING_NUM_CTX": ("embedding", "num_ctx"),
        "RAGKB_EMBEDDING_FAKE_DIM": ("embedding", "fake_dim"),
        "RAGKB_STORE_BACKEND": ("store", "backend"),
        "RAGKB_CHROMA_HOST": ("store", "chroma_host"),
        "RAGKB_CHROMA_COLLECTION": ("store", "collection"),
        "RAGKB_LLM_BACKEND": ("llm", "backend"),
        "RAGKB_LLM_MODEL": ("llm", "model"),
        "RAGKB_LLM_URL": ("llm", "base_url"),
        "RAGKB_LLM_API_KEY": ("llm", "api_key"),
        "RAGKB_BM25_WEIGHT": ("retrieval", "bm25_weight"),
        "RAGKB_DENSE_WEIGHT": ("retrieval", "dense_weight"),
        "RAGKB_RRF_K": ("retrieval", "rrf_k"),
        "RAGKB_DEDUPE_TEXT": ("retrieval", "dedupe_text"),
        "RAGKB_RERANKER": ("retrieval", "reranker"),
        "RAGKB_RERANKER_MODEL": ("retrieval", "reranker_model"),
        "RAGKB_RERANKER_URL": ("retrieval", "reranker_url"),
        "RAGKB_RERANKER_API_KEY": ("retrieval", "reranker_api_key"),
        "RAGKB_MIN_RERANK_SCORE": ("retrieval", "min_rerank_score"),
        "RAGKB_ORG_NAME": ("organization", "name"),
        "RAGKB_ORG_ID": ("organization", "id"),
        "RAGKB_LOG_LEVEL": ("logging", "level"),
        "RAGKB_LOG_DIR": ("logging", "dir"),
    }

    @classmethod
    def env_overrides(cls) -> dict[str, tuple[str | None, str]]:
        """Таблица «переменная окружения → путь в конфигурации».

        Нужна странице настроек: она показывает, какие значения пришли из
        окружения, а какие выставлены в интерфейсе.
        """
        return dict(cls._ENV)

    def model_post_init(self, __context: Any) -> None:
        self._apply_env()

    def _apply_env(self) -> None:
        for env, (section, attr) in self._ENV.items():
            value = os.environ.get(env)
            if not value:
                continue
            target = self if section is None else getattr(self, section)
            # Значение приходит строкой, а поле может быть числом или флагом:
            # без приведения «0.7» из окружения сломало бы арифметику.
            setattr(target, attr, _coerce(getattr(target, attr), value))

    @property
    def db_url(self) -> str:
        creds = f"{quote_plus(self.postgresql_user)}:{quote_plus(self.postgresql_password)}"
        # Без @host SQLAlchemy читает пароль как порт. Compose-сервис
        # называется postgres; локально хост задают POSTGRES_HOST.
        host = self.postgresql_host or "postgres"
        return f"postgresql+asyncpg://{creds}@{host}/{quote_plus(self.postgresql_db)}"

    @property
    def database_url(self) -> str:
        explicit = getattr(self, "_database_url", None)
        if explicit is not None:
            return explicit
        if self.database_url_override:
            return self.database_url_override
        if self.postgresql_user and self.postgresql_password and self.postgresql_db:
            return self.db_url
        return ""

    @database_url.setter
    def database_url(self, value: str) -> None:
        self._database_url = value


def _coerce(current: Any, value: str) -> Any:
    """Приводит строку окружения к типу текущего значения поля.

    Некорректное значение не роняет старт сервиса: переменная окружения —
    не то место, где стоит падать, оставим прежнее значение и продолжим.
    """
    text = value.strip()
    if isinstance(current, bool):
        return text.lower() not in {"false", "0", "no", "off"}
    if isinstance(current, int):
        try:
            return int(text)
        except ValueError:
            return current
    if isinstance(current, float):
        try:
            return float(text)
        except ValueError:
            return current
    return value
