"""Бэкенды эмбеддингов.

Все возвращают L2-нормализованные векторы (numpy float32), поэтому скалярное
произведение = косинусная близость.

Выбор бэкенда:
  openai                — OpenAI-совместимый HTTP: /v1/embeddings (vLLM, Infinity,
                          llama.cpp, облако). Основной боевой путь.
  sentence-transformers — модель уже на диске, без HTTP
  ollama                — нативный /api/embeddings; в compose его нет
  tfidf                 — без нейросетей: baseline и CI
"""
from __future__ import annotations

import math
from abc import ABC, abstractmethod
from collections import Counter
from collections.abc import Sequence
from typing import Any

import numpy as np

from .config import EmbeddingConfig
from .text import tokenize


class Embedder(ABC):
    dim: int
    name: str

    @abstractmethod
    def embed_documents(self, texts: Sequence[str]) -> np.ndarray: ...

    @abstractmethod
    def embed_query(self, text: str) -> np.ndarray: ...

    # Состояние (например, словарь TF-IDF) сохраняется вместе с индексом.
    def state(self) -> dict[str, Any]:
        return {}

    def load_state(self, state: dict[str, Any]) -> None:
        return None


def build_embedder(cfg: EmbeddingConfig) -> Embedder:
    backend = cfg.backend.lower()
    if backend == "ollama":
        return OllamaEmbedder(cfg)
    if backend in {"sentence-transformers", "st", "hf"}:
        return SentenceTransformerEmbedder(cfg)
    if backend == "openai":
        return OpenAIEmbedder(cfg)
    if backend == "tfidf":
        return TfidfEmbedder(cfg)
    raise ValueError(f"Неизвестный бэкенд эмбеддингов: {cfg.backend}")


def normalize_rows(matrix: np.ndarray) -> np.ndarray:
    matrix = np.asarray(matrix, dtype=np.float32)
    if matrix.ndim == 1:
        matrix = matrix.reshape(1, -1)
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return matrix / norms


# ------------------------------------------------------------------- Ollama

class OllamaEmbedder(Embedder):
    """Локальный Ollama. Модели: bge-m3, nomic-embed-text, multilingual-e5-large."""

    def __init__(self, cfg: EmbeddingConfig):
        self.cfg = cfg
        self.name = f"ollama:{cfg.model}"
        self.base_url = cfg.base_url.rstrip("/")
        self._dim: int | None = None

    @property
    def dim(self) -> int:  # type: ignore[override]
        if self._dim is None:
            self._dim = int(self.embed_query("проверка").shape[-1])
        return self._dim

    def _post(self, texts: list[str]) -> np.ndarray:
        import httpx

        vectors: list[list[float]] = []
        with httpx.Client(timeout=120) as client:
            for i in range(0, len(texts), self.cfg.batch_size):
                batch = texts[i : i + self.cfg.batch_size]
                resp = client.post(
                    f"{self.base_url}/api/embed",
                    json={"model": self.cfg.model, "input": batch},
                )
                resp.raise_for_status()
                vectors.extend(resp.json()["embeddings"])
        return normalize_rows(np.array(vectors, dtype=np.float32))

    def embed_documents(self, texts: Sequence[str]) -> np.ndarray:
        return self._post([self.cfg.doc_prefix + t for t in texts])

    def embed_query(self, text: str) -> np.ndarray:
        return self._post([self.cfg.query_prefix + text])[0]


# ------------------------------------------------------- sentence-transformers

class SentenceTransformerEmbedder(Embedder):
    def __init__(self, cfg: EmbeddingConfig):
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError(
                "pip install sentence-transformers — либо используйте backend=openai/tfidf"
            ) from exc
        self.cfg = cfg
        self.model = SentenceTransformer(cfg.model)
        self.name = f"st:{cfg.model}"
        self.dim = int(self.model.get_sentence_embedding_dimension())

    def embed_documents(self, texts: Sequence[str]) -> np.ndarray:
        vecs = self.model.encode(
            [self.cfg.doc_prefix + t for t in texts],
            batch_size=self.cfg.batch_size,
            show_progress_bar=False,
            convert_to_numpy=True,
        )
        return normalize_rows(vecs)

    def embed_query(self, text: str) -> np.ndarray:
        vec = self.model.encode([self.cfg.query_prefix + text], convert_to_numpy=True)
        return normalize_rows(vec)[0]


# ------------------------------------------------------------------- OpenAI-like

class OpenAIEmbedder(Embedder):
    def __init__(self, cfg: EmbeddingConfig):
        self.cfg = cfg
        self.name = f"openai:{cfg.model}"
        self.base_url = cfg.base_url.rstrip("/")
        self._dim: int | None = None

    @property
    def dim(self) -> int:  # type: ignore[override]
        if self._dim is None:
            self._dim = int(self.embed_query("проверка").shape[-1])
        return self._dim

    def _post(self, texts: list[str]) -> np.ndarray:
        import httpx

        headers = {"Authorization": f"Bearer {self.cfg.api_key}"} if self.cfg.api_key else {}
        vectors: list[list[float]] = []
        with httpx.Client(timeout=120, headers=headers) as client:
            for i in range(0, len(texts), self.cfg.batch_size):
                batch = texts[i : i + self.cfg.batch_size]
                resp = client.post(
                    f"{self.base_url}/embeddings",
                    json={"model": self.cfg.model, "input": batch},
                )
                resp.raise_for_status()
                data = sorted(resp.json()["data"], key=lambda d: d["index"])
                vectors.extend(d["embedding"] for d in data)
        return normalize_rows(np.array(vectors, dtype=np.float32))

    def embed_documents(self, texts: Sequence[str]) -> np.ndarray:
        return self._post([self.cfg.doc_prefix + t for t in texts])

    def embed_query(self, text: str) -> np.ndarray:
        return self._post([self.cfg.query_prefix + text])[0]


# -------------------------------------------------------------------- TF-IDF

class TfidfEmbedder(Embedder):
    """Разреженный TF-IDF, спроецированный в плотный вектор фиксированной длины.

    Не требует ни моделей, ни сети. Ловит лексические совпадения, но не синонимы —
    поэтому в гибридной схеме он вносит примерно то же, что BM25. Держим его
    как baseline и как способ прогнать пайплайн в CI без GPU и без интернета.
    """

    def __init__(self, cfg: EmbeddingConfig):
        self.cfg = cfg
        self.name = "tfidf"
        self.dim = cfg.tfidf_dim
        self.idf: dict[str, float] = {}
        self._n_docs = 0

    def fit(self, texts: Sequence[str]) -> None:
        df: Counter[str] = Counter()
        for text in texts:
            df.update(set(tokenize(text)))
        self._n_docs = max(1, len(texts))
        self.idf = {
            term: math.log((self._n_docs + 1) / (count + 1)) + 1.0
            for term, count in df.items()
        }

    def _vector(self, text: str) -> np.ndarray:
        vec = np.zeros(self.dim, dtype=np.float32)
        counts = Counter(tokenize(text))
        if not counts:
            return vec
        max_tf = max(counts.values())
        for term, tf in counts.items():
            weight = (0.5 + 0.5 * tf / max_tf) * self.idf.get(term, 1.0)
            # Hashing trick: два хэша уменьшают эффект коллизий.
            for salt in (b"", b"#"):
                idx = _stable_hash(term.encode() + salt) % self.dim
                vec[idx] += weight
        return vec

    def embed_documents(self, texts: Sequence[str]) -> np.ndarray:
        if not self.idf:
            self.fit(texts)
        return normalize_rows(np.vstack([self._vector(t) for t in texts]))

    def embed_query(self, text: str) -> np.ndarray:
        return normalize_rows(self._vector(text))[0]

    def state(self) -> dict[str, Any]:
        return {"idf": self.idf, "n_docs": self._n_docs}

    def load_state(self, state: dict[str, Any]) -> None:
        self.idf = {k: float(v) for k, v in (state.get("idf") or {}).items()}
        self._n_docs = int(state.get("n_docs", 0))


def _stable_hash(data: bytes) -> int:
    """FNV-1a: детерминирован между запусками, в отличие от встроенного hash()."""
    h = 0xCBF29CE484222325
    for byte in data:
        h ^= byte
        h = (h * 0x100000001B3) & 0xFFFFFFFFFFFFFFFF
    return h
