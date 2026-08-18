"""Конфигурация системы. Всё настраивается через YAML или переменные окружения."""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class ChunkConfig:
    # Размер чанка в символах. ~800 символов ≈ 200-250 токенов для русского текста.
    size: int = 900
    overlap: int = 150
    # Не резать чанки короче — такие куски склеиваются с соседями.
    min_size: int = 120
    # Уважать границы структуры (заголовки, абзацы) при нарезке.
    respect_structure: bool = True


@dataclass
class EmbeddingConfig:
    # backend: "ollama" | "sentence-transformers" | "openai" | "tfidf"
    backend: str = "tfidf"
    model: str = "bge-m3"
    # Для ollama / openai-совместимых серверов
    base_url: str = "http://localhost:11434"
    api_key: str = ""
    batch_size: int = 32
    # e5-модели требуют префиксов "query: " / "passage: "
    query_prefix: str = ""
    doc_prefix: str = ""
    # Размерность для tfidf-фолбэка
    tfidf_dim: int = 4096


@dataclass
class StoreConfig:
    # backend: "chroma" | "numpy"
    backend: str = "chroma"
    collection: str = "knowledge_base"
    # Пусто — встроенный режим (файлы рядом с индексом).
    # Заполнено — подключение к отдельному серверу Chroma.
    chroma_host: str = ""
    chroma_port: int = 8000
    upsert_batch: int = 500
    # Параметры HNSW. construction_ef и M влияют на качество индекса и время
    # сборки, search_ef — на полноту поиска в рантайме.
    hnsw_construction_ef: int = 200
    hnsw_search_ef: int = 100
    hnsw_m: int = 16


@dataclass
class RetrievalConfig:
    top_k: int = 5              # сколько чанков уходит в промпт
    candidates: int = 30        # сколько кандидатов достаём до реранка
    use_bm25: bool = True
    use_dense: bool = True
    rrf_k: int = 60             # константа Reciprocal Rank Fusion
    # MMR — снижает дублирование в выдаче. 1.0 = только релевантность, 0.0 = только разнообразие.
    mmr_lambda: float = 0.7
    use_mmr: bool = True
    # Порог косинусной близости: ниже — считаем, что ответа в базе нет.
    min_score: float = 0.0
    # Реранкер (cross-encoder). "none" | "sentence-transformers"
    reranker: str = "none"
    reranker_model: str = "BAAI/bge-reranker-v2-m3"


@dataclass
class LLMConfig:
    # backend: "ollama" | "openai" | "extractive"
    backend: str = "extractive"
    model: str = "qwen2.5:7b-instruct"
    base_url: str = "http://localhost:11434"
    api_key: str = ""
    temperature: float = 0.1
    max_tokens: int = 1024
    timeout: int = 180


@dataclass
class Config:
    # Где лежат исходные документы и где хранится индекс.
    docs_dir: str = "data/docs"
    index_dir: str = "data/index"
    language: str = "ru"
    chunking: ChunkConfig = field(default_factory=ChunkConfig)
    embedding: EmbeddingConfig = field(default_factory=EmbeddingConfig)
    store: StoreConfig = field(default_factory=StoreConfig)
    retrieval: RetrievalConfig = field(default_factory=RetrievalConfig)
    llm: LLMConfig = field(default_factory=LLMConfig)

    @classmethod
    def load(cls, path: str | os.PathLike | None = None) -> "Config":
        data: dict[str, Any] = {}
        if path and Path(path).exists():
            text = Path(path).read_text(encoding="utf-8")
            if str(path).endswith((".yaml", ".yml")):
                data = _load_yaml(text)
            else:
                data = json.loads(text)
        cfg = cls.from_dict(data)
        cfg._apply_env()
        return cfg

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Config":
        sections = {
            "chunking": ChunkConfig,
            "embedding": EmbeddingConfig,
            "store": StoreConfig,
            "retrieval": RetrievalConfig,
            "llm": LLMConfig,
        }
        kwargs: dict[str, Any] = {}
        for key, value in (data or {}).items():
            if key in sections:
                kwargs[key] = sections[key](**value)
            else:
                kwargs[key] = value
        return cls(**kwargs)

    def _apply_env(self) -> None:
        """Переменные окружения перекрывают файл: RAGKB_LLM_BACKEND, RAGKB_EMBEDDING_MODEL и т.д."""
        mapping = {
            "RAGKB_DOCS_DIR": ("docs_dir", self),
            "RAGKB_INDEX_DIR": ("index_dir", self),
            "RAGKB_EMBEDDING_BACKEND": ("backend", self.embedding),
            "RAGKB_EMBEDDING_MODEL": ("model", self.embedding),
            "RAGKB_EMBEDDING_URL": ("base_url", self.embedding),
            "RAGKB_STORE_BACKEND": ("backend", self.store),
            "RAGKB_CHROMA_HOST": ("chroma_host", self.store),
            "RAGKB_CHROMA_COLLECTION": ("collection", self.store),
            "RAGKB_LLM_BACKEND": ("backend", self.llm),
            "RAGKB_LLM_MODEL": ("model", self.llm),
            "RAGKB_LLM_URL": ("base_url", self.llm),
            "RAGKB_LLM_API_KEY": ("api_key", self.llm),
        }
        for env, (attr, target) in mapping.items():
            val = os.environ.get(env)
            if val:
                setattr(target, attr, val)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _load_yaml(text: str) -> dict[str, Any]:
    try:
        import yaml  # type: ignore
        return yaml.safe_load(text) or {}
    except ImportError:
        return _mini_yaml(text)


def _mini_yaml(text: str) -> dict[str, Any]:
    """Минимальный парсер YAML на случай, если pyyaml не установлен.

    Поддерживает только два уровня вложенности и скалярные значения —
    ровно то, что нужно для нашего конфига.
    """
    root: dict[str, Any] = {}
    current: dict[str, Any] = root
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip())
        key, _, value = line.strip().partition(":")
        value = value.strip()
        if not value:
            current = {}
            root[key] = current
            continue
        target = current if indent > 0 else root
        target[key] = _coerce(value)
    return root


def _coerce(value: str) -> Any:
    low = value.lower()
    if low in {"true", "false"}:
        return low == "true"
    if low in {"null", "none", "~"}:
        return None
    for cast in (int, float):
        try:
            return cast(value)
        except ValueError:
            pass
    return value.strip("'\"")
