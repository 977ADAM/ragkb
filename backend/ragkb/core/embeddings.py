"""Бэкенды эмбеддингов.

Все возвращают L2-нормализованные векторы (numpy float32), поэтому скалярное
произведение = косинусная близость.

Выбор бэкенда:
  ollama                — основной путь: модель живёт в Ollama, запросы идут
                          в нативный /api/embed. В образе сервиса нет ни torch,
                          ни весов модели.
  openai                — OpenAI-совместимый HTTP: /v1/embeddings (vLLM, Infinity,
                          llama.cpp, облако).
  sentence-transformers — HuggingFace Hub (transformers) в процессе сервиса;
                          требует extra local-models, в образе его нет
  tfidf                 — без нейросетей: baseline и тесты
"""
from __future__ import annotations

import math
import threading
import time
from abc import ABC, abstractmethod
from collections import Counter
from collections.abc import Sequence
from typing import Any

import numpy as np

from .config import Settings
from .errors import EngineUnavailable
from .text import tokenize

# Пауза перед повтором: индексация идёт долго, а Ollama может перезапускаться.
_RETRY_BACKOFF = 0.5


class Embedder(ABC):
    dim: int
    name: str

    @abstractmethod
    def embed_documents(self, texts: Sequence[str]) -> np.ndarray: ...

    @abstractmethod
    def embed_query(self, text: str) -> np.ndarray: ...

    def check(self) -> None:
        """Предпроверка перед тяжёлой работой: бэкенд готов считать векторы.

        Нужна там, где отказ модели стоит дорого: полная переиндексация
        парсит и чанкует корпус до первого обращения к эмбеддеру. Локальным
        бэкендам (tfidf, sentence-transformers) проверять нечего.
        """
        return None

    # Состояние (например, словарь TF-IDF) сохраняется вместе с индексом.
    def state(self) -> dict[str, Any]:
        return {}

    def load_state(self, state: dict[str, Any]) -> None:
        return None


def build_embedder(cfg: Settings.EmbeddingConfig) -> Embedder:
    """Эмбеддер для конфигурации — один на процесс.

    Модель весит гигабайты и грузится десятки секунд на CPU. Движок при этом
    пересобирается после каждой переиндексации, и без кеша каждая пересборка
    (и каждое открытие страницы документов) поднимала модель заново. Ключ —
    параметры эмбеддинга: смена модели в конфиге даёт свой объект.

    Состояние (словарь TF-IDF) эмбеддер получает из индекса при сборке
    движка, поэтому переиспользование объекта не мешает.
    """
    key = (
        cfg.backend.lower(),
        cfg.model,
        cfg.base_url,
        cfg.api_key,
        cfg.doc_prefix,
        cfg.query_prefix,
        cfg.tfidf_dim,
        cfg.batch_size,
        cfg.timeout,
        cfg.keep_alive,
        cfg.retries,
    )
    with _EMBEDDER_LOCK:
        embedder = _EMBEDDERS.get(key)
        if embedder is None:
            embedder = _create_embedder(cfg)
            _EMBEDDERS[key] = embedder
        return embedder


def _create_embedder(cfg: Settings.EmbeddingConfig) -> Embedder:
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


# Кеш живёт на процесс: uvicorn держит один интерпретатор, потоков может быть
# несколько, поэтому доступ под замком.
_EMBEDDERS: dict[tuple[Any, ...], Embedder] = {}
_EMBEDDER_LOCK = threading.Lock()


def normalize_rows(matrix: np.ndarray) -> np.ndarray:
    matrix = np.asarray(matrix, dtype=np.float32)
    if matrix.ndim == 1:
        matrix = matrix.reshape(1, -1)
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return matrix / norms


# ------------------------------------------------------------------- Ollama

def _embedding_length(shown: dict[str, Any]) -> int:
    """Длина вектора из ответа /api/show: ключ вида «qwen3.embedding_length»."""
    for key, value in (shown.get("model_info") or {}).items():
        if key.endswith("embedding_length") and isinstance(value, int) and value > 0:
            return int(value)
    return 0


class OllamaEmbedder(Embedder):
    """Эмбеддинги из Ollama: нативный /api/embed.

    Модель живёт не в процессе сервиса, поэтому важно сверять её имя: индекс,
    собранный одной моделью, нельзя искать векторами другой — имя вида
    ollama:<тег> попадает в манифест и проверяется при сборке движка.

    Подходят модели с возможностью embedding: qwen3-embedding, bge-m3,
    nomic-embed-text, mxbai-embed-large, embeddinggemma.
    """

    def __init__(
        self,
        cfg: Settings.EmbeddingConfig,
        transport: Any | None = None,
    ):
        self.cfg = cfg
        self.name = f"ollama:{cfg.model}"
        self.base_url = cfg.base_url.rstrip("/")
        # Подменяемый транспорт — для тестов без сети (httpx.MockTransport).
        self._transport = transport
        self._dim: int | None = None
        if not self.base_url:
            raise EngineUnavailable(
                "Не задан адрес Ollama: укажите embedding.base_url "
                "(RAGKB_EMBEDDING_URL), например http://127.0.0.1:11434"
            )

    # ------------------------------------------------------------- транспорт

    def _client(self):
        import httpx

        return httpx.Client(
            base_url=self.base_url,
            timeout=httpx.Timeout(float(self.cfg.timeout)),
            transport=self._transport,
        )

    def _request(self, client, method: str, url: str, **kwargs):
        """Запрос с повторами. Возвращает только успешный ответ.

        Повторяем сетевые сбои, 5xx и 429: Ollama может перезапускаться или
        грузить модель. Ответ 4xx повторять бессмысленно — это ошибка настройки.
        """
        import httpx

        attempts = max(1, int(self.cfg.retries))
        reason = "Ollama не ответила"
        for attempt in range(1, attempts + 1):
            try:
                response = client.request(method, url, **kwargs)
            except httpx.HTTPError as exc:
                reason = self._unreachable(exc)
            else:
                if response.status_code < 400:
                    return response
                reason = self._rejected(response)
                if response.status_code < 500 and response.status_code != 429:
                    break
            if attempt < attempts:
                time.sleep(_RETRY_BACKOFF * attempt)
        raise EngineUnavailable(reason)

    def _unreachable(self, exc: Exception) -> str:
        return (
            f"Ollama недоступна по адресу {self.base_url} ({exc.__class__.__name__}). "
            f"Запустите `ollama serve` или укажите её адрес в RAGKB_EMBEDDING_URL"
        )

    def _rejected(self, response) -> str:
        detail = ""
        try:
            body = response.json()
        except ValueError:
            body = None
        if isinstance(body, dict):
            detail = str(body.get("error") or body.get("detail") or "")
        detail = detail or (response.text or "")[:200]
        hint = ""
        if response.status_code == 404:
            hint = (
                f" Модель «{self.cfg.model}» не установлена — выполните: "
                f"ollama pull {self.cfg.model}"
            )
        return (
            f"Ollama отклонила запрос ({response.status_code}) по адресу "
            f"{self.base_url}: {detail or 'без пояснения'}.{hint}"
        )

    # -------------------------------------------------------------- проверка

    def check(self) -> None:
        """Модель установлена и умеет считать эмбеддинги — до тяжёлой работы.

        Заодно узнаём длину вектора: /api/show отдаёт метаданные модели, не
        считая ни одного эмбеддинга.
        """
        try:
            with self._client() as client:
                shown = self._request(
                    client, "POST", "/api/show", json={"model": self.cfg.model}
                )
        except EngineUnavailable as exc:
            # «Модель не установлена» без списка того, что есть, — половина
            # ответа: администратору нужно знать, чем заменить имя в конфиге.
            raise EngineUnavailable(f"{exc.detail}{self._installed_hint()}") from exc
        try:
            body = shown.json()
        except ValueError as exc:
            raise EngineUnavailable(
                f"Ollama вернула не JSON на /api/show для модели «{self.cfg.model}»: {exc}"
            ) from exc
        capabilities = body.get("capabilities") or []
        if capabilities and "embedding" not in capabilities:
            raise EngineUnavailable(
                f"Модель «{self.cfg.model}» в Ollama не считает эмбеддинги "
                f"(умеет: {', '.join(capabilities)}). Нужна модель эмбеддингов, "
                f"например qwen3-embedding:0.6b"
            )
        self._dim = _embedding_length(body) or self._dim

    def installed(self) -> list[str]:
        """Имена моделей в Ollama — для понятного текста об отсутствующей модели."""
        with self._client() as client:
            response = self._request(client, "GET", "/api/tags")
        try:
            entries = response.json().get("models") or []
        except ValueError:
            return []
        names = [str(entry.get("name") or entry.get("model") or "") for entry in entries]
        return [name for name in names if name]

    def _installed_hint(self) -> str:
        try:
            names = self.installed()
        except EngineUnavailable:
            return ""
        return f" Установлены: {', '.join(sorted(names))}." if names else ""

    @property
    def dim(self) -> int:  # type: ignore[override]
        """Длина вектора: из /api/show, иначе — коротким запросом эмбеддинга."""
        if self._dim is None:
            self.check()
        if self._dim is None:
            self._dim = int(self.embed_query("проверка").shape[-1])
        return self._dim

    # ------------------------------------------------------------ эмбеддинги

    def _post(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, 0), dtype=np.float32)
        batch_size = max(1, int(self.cfg.batch_size))
        payload: dict[str, Any] = {"model": self.cfg.model, "truncate": True}
        if self.cfg.keep_alive:
            payload["keep_alive"] = self.cfg.keep_alive
        vectors: list[list[float]] = []
        with self._client() as client:
            for start in range(0, len(texts), batch_size):
                batch = texts[start : start + batch_size]
                response = self._request(
                    client, "POST", "/api/embed", json={**payload, "input": batch}
                )
                try:
                    part = response.json().get("embeddings") or []
                except ValueError as exc:
                    raise EngineUnavailable(
                        f"Ollama вернула не JSON на запрос эмбеддингов: {exc}"
                    ) from exc
                if len(part) != len(batch):
                    raise EngineUnavailable(
                        f"Ollama вернула {len(part)} векторов на {len(batch)} текстов "
                        f"моделью «{self.cfg.model}» — пакетный запрос отклонён"
                    )
                vectors.extend(part)
        matrix = normalize_rows(np.array(vectors, dtype=np.float32))
        # Размерность известна точно — запоминаем вместо отдельной пробы.
        self._dim = int(matrix.shape[-1])
        return matrix

    def embed_documents(self, texts: Sequence[str]) -> np.ndarray:
        return self._post([self.cfg.doc_prefix + text for text in texts])

    def embed_query(self, text: str) -> np.ndarray:
        return self._post([self.cfg.query_prefix + text])[0]


# ------------------------------------------------------- sentence-transformers

class SentenceTransformerEmbedder(Embedder):
    def __init__(self, cfg: Settings.EmbeddingConfig):
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError(
                "sentence-transformers не установлен (в образе его нет: "
                "эмбеддинги берутся из Ollama). Локально: "
                "pip install 'ragkb[local-models]' либо backend=ollama/tfidf"
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
    def __init__(self, cfg: Settings.EmbeddingConfig):
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

    def __init__(self, cfg: Settings.EmbeddingConfig):
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
