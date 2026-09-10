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
        rrf_k: int = 60
        use_mmr: bool = True
        mmr_lambda: float = 0.7
        min_score: float = 0.0
        reranker: str = "none"
        reranker_model: str = "BAAI/bge-reranker-v2-m3"

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
            setattr(target, attr, value)
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
