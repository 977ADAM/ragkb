from __future__ import annotations

import os
from typing import Any, ClassVar
from urllib.parse import quote_plus

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    class ChunkConfig(BaseModel):
        size: int = 900
        overlap: int = 150
        min_size: int = 120
        respect_structure: bool = True

    class EmbeddingConfig(BaseModel):
        backend: str = "tfidf"
        model: str = "BAAI/bge-m3"
        base_url: str = ""
        api_key: str = ""
        batch_size: int = 32
        query_prefix: str = ""
        doc_prefix: str = ""
        tfidf_dim: int = 4096

    class StoreConfig(BaseModel):
        backend: str = "chroma"
        collection: str = "knowledge_base"
        chroma_host: str = ""
        chroma_port: int = 8000
        upsert_batch: int = 500
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
        min_score: float = 0.0
        # Одинаковый текст из двух файлов не должен занимать в выдаче две
        # позиции: он вытесняет альтернативные формулировки.
        dedupe_text: bool = True
        reranker: str = "none"          # none | sentence-transformers | http
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
        backend: str = "extractive"
        model: str = ""
        base_url: str = ""
        api_key: str = ""
        temperature: float = 0.1
        max_tokens: int = 256
        timeout: int = 600
        available: list[dict[str, str]] = []

    class AuthConfig(BaseModel):
        mode: str = "disabled"
        header: str = "X-Forwarded-Preferred-Username"
        email_header: str = "X-Forwarded-Email"
        groups_header: str = "X-Forwarded-Groups"
        admin_group: str = "ragkb-admins"

    class OrganizationConfig(BaseModel):
        name: str = ""
        id: str = ""
        description: str = ""

    class HistoryConfig(BaseModel):
        enabled: bool = True
        retention_days: int = 90
        window: int = 3

    class LoggingConfig(BaseModel):
        level: str = "INFO"
        dir: str = "data/logs"

    model_config: ClassVar[SettingsConfigDict] = SettingsConfigDict(
        env_file=os.environ.get("ENV_FILE", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    docs_dir: str = "data/docs"
    index_dir: str = "data/index"
    language: str = "ru"
    chunking: ChunkConfig = ChunkConfig()
    embedding: EmbeddingConfig = EmbeddingConfig()
    store: StoreConfig = StoreConfig()
    retrieval: RetrievalConfig = RetrievalConfig()
    llm: LLMConfig = LLMConfig()
    auth: AuthConfig = AuthConfig()
    organization: OrganizationConfig = OrganizationConfig()
    history: HistoryConfig = HistoryConfig()
    logging: LoggingConfig = LoggingConfig()

    postgresql_password: str = Field(default="", validation_alias="POSTGRES_PASSWORD")
    postgresql_user: str = Field(default="", validation_alias="POSTGRES_USER")
    postgresql_db: str = Field(default="", validation_alias="POSTGRES_DB")
    postgresql_host: str = Field(default="", validation_alias="POSTGRES_HOST")

    _ENV: ClassVar[dict[str, tuple[str | None, str]]] = {
        "RAGKB_DOCS_DIR": (None, "docs_dir"),
        "RAGKB_INDEX_DIR": (None, "index_dir"),
        "RAGKB_EMBEDDING_BACKEND": ("embedding", "backend"),
        "RAGKB_EMBEDDING_MODEL": ("embedding", "model"),
        "RAGKB_EMBEDDING_URL": ("embedding", "base_url"),
        "RAGKB_EMBEDDING_API_KEY": ("embedding", "api_key"),
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
        "RAGKB_AUTH_MODE": ("auth", "mode"),
        "RAGKB_AUTH_HEADER": ("auth", "header"),
        "RAGKB_AUTH_GROUPS_HEADER": ("auth", "groups_header"),
        "RAGKB_AUTH_EMAIL_HEADER": ("auth", "email_header"),
        "RAGKB_AUTH_ADMIN_GROUP": ("auth", "admin_group"),
        "RAGKB_ORG_NAME": ("organization", "name"),
        "RAGKB_ORG_ID": ("organization", "id"),
        "RAGKB_LOG_LEVEL": ("logging", "level"),
        "RAGKB_LOG_DIR": ("logging", "dir"),
    }

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
        raw_history = os.environ.get("RAGKB_HISTORY_ENABLED")
        if raw_history not in (None, ""):
            self.history.enabled = raw_history.strip().lower() not in {
                "false",
                "0",
                "no",
            }

    @property
    def db_url(self) -> str:
        creds = f"{quote_plus(self.postgresql_user)}:{quote_plus(self.postgresql_password)}"
        host = f"@{self.postgresql_host}" if self.postgresql_host else ""
        return f"postgresql+asyncpg://{creds}{host}/{quote_plus(self.postgresql_db)}"

    @property
    def database_url(self) -> str:
        explicit = getattr(self, "_database_url", None)
        if explicit is not None:
            return explicit
        env_url = os.environ.get("RAGKB_DATABASE_URL")
        if env_url:
            return env_url
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
