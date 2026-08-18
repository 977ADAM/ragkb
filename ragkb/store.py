"""Хранилища чанков.

Два бэкенда за одним интерфейсом:

  chroma — ChromaDB. Персистентный клиент, HNSW-индекс, фильтры по метаданным,
           инкрементальное добавление и удаление документов без переиндексации.
  numpy  — матрица в памяти и brute-force перебор. Ноль внешних зависимостей,
           точный поиск, удобен для тестов и небольших корпусов.

Лексический поиск (BM25) в обоих случаях наш собственный: Chroma умеет
полнотекстовый фильтр `where_document`, но это фильтр по вхождению подстроки,
а не ранжирование, и для гибридной схемы он не годится.

Интерфейс намеренно узкий — поиск возвращает пары (chunk_id, score), поэтому
слой ранжирования не знает, чем хранятся векторы.
"""
from __future__ import annotations

import json
import re
import shutil
from abc import ABC, abstractmethod
from dataclasses import asdict
from pathlib import Path
from typing import Any, Iterable, Sequence

import numpy as np

from .bm25 import BM25Index
from .chunking import Chunk
from .config import Config, StoreConfig

MANIFEST = "manifest.json"
VECTORS = "vectors.npy"
CHUNKS = "chunks.jsonl"
BM25_FILE = "bm25.pkl"
EMBEDDER_STATE = "embedder_state.json"
CHROMA_SUBDIR = "chroma"


# --------------------------------------------------------------------- интерфейс

class BaseStore(ABC):
    """Общий контракт хранилища."""

    def __init__(self, index_dir: str | Path):
        self.dir = Path(index_dir)
        self.chunks: list[Chunk] = []
        self.manifest: dict[str, Any] = {}
        self.bm25 = BM25Index()
        self._embedder_state: dict[str, Any] = {}
        self._by_id: dict[str, Chunk] = {}

    # -------------------------------------------------------------- запись

    @abstractmethod
    def build(
        self,
        chunks: list[Chunk],
        vectors: np.ndarray,
        *,
        embedder_name: str = "",
        embedder_state: dict[str, Any] | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None: ...

    @abstractmethod
    def save(self) -> None: ...

    # -------------------------------------------------------------- поиск

    @abstractmethod
    def dense_search(self, query_vector: np.ndarray, top_k: int) -> list[tuple[str, float]]:
        """Возвращает [(chunk_id, косинусная близость)], отсортированные по убыванию."""

    @abstractmethod
    def get_vectors(self, chunk_ids: Sequence[str]) -> np.ndarray:
        """Векторы указанных чанков в том же порядке — нужны для MMR."""

    def lexical_search(self, query: str, top_k: int) -> list[tuple[str, float]]:
        rows = self.bm25.search(query, top_k)
        return [(self.chunks[row].chunk_id, score) for row, score in rows]

    # ----------------------------------------------------------- служебное

    def get_chunk(self, chunk_id: str) -> Chunk:
        return self._by_id[chunk_id]

    @property
    def embedder_state(self) -> dict[str, Any]:
        return self._embedder_state

    def exists(self) -> bool:
        return (self.dir / MANIFEST).exists()

    def clear(self) -> None:
        if self.dir.exists():
            shutil.rmtree(self.dir)

    def __len__(self) -> int:
        return len(self.chunks)

    def _reindex_lookup(self) -> None:
        self._by_id = {c.chunk_id: c for c in self.chunks}

    def _write_common(self) -> None:
        """Метаданные, чанки и BM25 хранятся одинаково для всех бэкендов."""
        self.dir.mkdir(parents=True, exist_ok=True)
        with (self.dir / CHUNKS).open("w", encoding="utf-8") as fh:
            for chunk in self.chunks:
                fh.write(json.dumps(asdict(chunk), ensure_ascii=False) + "\n")
        self.bm25.save(self.dir / BM25_FILE)
        (self.dir / EMBEDDER_STATE).write_text(
            json.dumps(self._embedder_state, ensure_ascii=False), encoding="utf-8"
        )
        (self.dir / MANIFEST).write_text(
            json.dumps(self.manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def _read_common(self) -> None:
        if not (self.dir / MANIFEST).exists():
            raise FileNotFoundError(
                f"Индекс не найден в {self.dir}. Сначала выполните: ragkb index"
            )
        self.manifest = json.loads((self.dir / MANIFEST).read_text(encoding="utf-8"))
        self.chunks = [
            Chunk(**json.loads(line))
            for line in (self.dir / CHUNKS).read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        self.bm25 = BM25Index.load(self.dir / BM25_FILE)
        state_file = self.dir / EMBEDDER_STATE
        self._embedder_state = (
            json.loads(state_file.read_text(encoding="utf-8")) if state_file.exists() else {}
        )
        self._reindex_lookup()

    def _fill_manifest(
        self, chunks: list[Chunk], vectors: np.ndarray, embedder_name: str, extra: dict | None
    ) -> None:
        self.manifest = {
            "backend": self.backend_name,
            "n_chunks": len(chunks),
            "dim": int(vectors.shape[1]) if len(vectors) else 0,
            "embedder": embedder_name,
            "documents": _document_summary(chunks),
            **(extra or {}),
        }

    backend_name: str = "base"


# ------------------------------------------------------------------ numpy

class NumpyStore(BaseStore):
    """Точный brute-force поиск по матрице в памяти."""

    backend_name = "numpy"

    def __init__(self, index_dir: str | Path):
        super().__init__(index_dir)
        self.vectors: np.ndarray = np.zeros((0, 0), dtype=np.float32)

    def build(
        self,
        chunks: list[Chunk],
        vectors: np.ndarray,
        *,
        embedder_name: str = "",
        embedder_state: dict[str, Any] | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        if len(chunks) != len(vectors):
            raise ValueError("Число чанков и векторов должно совпадать")
        self.chunks = chunks
        self.vectors = np.ascontiguousarray(vectors, dtype=np.float32)
        self.bm25 = BM25Index().build([c.embed_text for c in chunks])
        self._embedder_state = embedder_state or {}
        self._fill_manifest(chunks, vectors, embedder_name, extra)
        self._reindex_lookup()

    def save(self) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        np.save(self.dir / VECTORS, self.vectors)
        self._write_common()

    @classmethod
    def load(cls, index_dir: str | Path) -> "NumpyStore":
        store = cls(index_dir)
        store._read_common()
        store.vectors = np.load(store.dir / VECTORS)
        return store

    def dense_search(self, query_vector: np.ndarray, top_k: int) -> list[tuple[str, float]]:
        if not len(self.vectors):
            return []
        # Векторы нормализованы → скалярное произведение = косинус.
        scores = self.vectors @ np.asarray(query_vector, dtype=np.float32)
        top_k = min(top_k, len(scores))
        idx = np.argpartition(-scores, top_k - 1)[:top_k]
        idx = idx[np.argsort(-scores[idx])]
        return [(self.chunks[int(i)].chunk_id, float(scores[i])) for i in idx]

    def get_vectors(self, chunk_ids: Sequence[str]) -> np.ndarray:
        rows = {c.chunk_id: i for i, c in enumerate(self.chunks)}
        return self.vectors[[rows[cid] for cid in chunk_ids]]


# ----------------------------------------------------------------- ChromaDB

class ChromaStore(BaseStore):
    """ChromaDB с персистентным клиентом.

    Векторы считаем сами (наш pluggable эмбеддер) и передаём готовыми —
    embedding_function у коллекции не задаётся. Это важно: иначе Chroma
    подставит свою модель по умолчанию, и индекс разойдётся с запросами.
    """

    backend_name = "chroma"

    def __init__(self, index_dir: str | Path, cfg: StoreConfig | None = None):
        super().__init__(index_dir)
        self.cfg = cfg or StoreConfig()
        self._client = None
        self._collection = None

    # ---------------------------------------------------------- клиент

    def _get_client(self):
        if self._client is not None:
            return self._client
        try:
            import chromadb
            from chromadb.config import Settings
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError(
                "ChromaDB не установлена: pip install chromadb "
                "(или переключитесь на store.backend: numpy)"
            ) from exc

        if self.cfg.chroma_host:
            # Отдельный сервер Chroma — если он уже развёрнут в контуре.
            self._client = chromadb.HttpClient(
                host=self.cfg.chroma_host,
                port=self.cfg.chroma_port,
                settings=Settings(anonymized_telemetry=False),
            )
        else:
            # Встроенный режим: база лежит файлами рядом с индексом.
            self._client = chromadb.PersistentClient(
                path=str(self.dir / CHROMA_SUBDIR),
                settings=Settings(anonymized_telemetry=False),
            )
        return self._client

    def _get_collection(self, create: bool = False, dim: int | None = None):
        if self._collection is not None:
            return self._collection
        _validate_collection_name(self.cfg.collection)
        client = self._get_client()
        metadata = {
            # Косинус, а не L2 по умолчанию: наши векторы нормализованы,
            # и косинус согласуется с тем, что считает numpy-бэкенд.
            "hnsw:space": "cosine",
            "hnsw:construction_ef": self.cfg.hnsw_construction_ef,
            "hnsw:search_ef": self.cfg.hnsw_search_ef,
            "hnsw:M": self.cfg.hnsw_m,
        }
        if create:
            try:
                client.delete_collection(self.cfg.collection)
            except Exception:
                pass  # коллекции ещё нет — это нормально
            self._collection = client.create_collection(
                name=self.cfg.collection, metadata=metadata, embedding_function=None
            )
        else:
            self._collection = client.get_collection(
                name=self.cfg.collection, embedding_function=None
            )
        return self._collection

    # ----------------------------------------------------------- запись

    def build(
        self,
        chunks: list[Chunk],
        vectors: np.ndarray,
        *,
        embedder_name: str = "",
        embedder_state: dict[str, Any] | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        if len(chunks) != len(vectors):
            raise ValueError("Число чанков и векторов должно совпадать")
        self.chunks = chunks
        self.bm25 = BM25Index().build([c.embed_text for c in chunks])
        self._embedder_state = embedder_state or {}
        self._fill_manifest(chunks, vectors, embedder_name, extra)
        self._reindex_lookup()

        collection = self._get_collection(create=True, dim=int(vectors.shape[1]))
        batch = self.cfg.upsert_batch
        for i in range(0, len(chunks), batch):
            part = chunks[i : i + batch]
            collection.add(
                ids=[c.chunk_id for c in part],
                embeddings=[v.tolist() for v in vectors[i : i + batch]],
                documents=[c.embed_text for c in part],
                metadatas=[_to_metadata(c) for c in part],
            )

    def save(self) -> None:
        # Chroma пишет на диск сама при add(); здесь сохраняем только
        # сопутствующее — чанки, BM25, манифест.
        self._write_common()

    @classmethod
    def load(cls, index_dir: str | Path, cfg: StoreConfig | None = None) -> "ChromaStore":
        store = cls(index_dir, cfg)
        store._read_common()
        store._get_collection(create=False)
        return store

    # ------------------------------------------------------------ поиск

    def dense_search(self, query_vector: np.ndarray, top_k: int) -> list[tuple[str, float]]:
        collection = self._get_collection()
        n = min(top_k, max(1, collection.count()))
        result = collection.query(
            query_embeddings=[np.asarray(query_vector, dtype=np.float32).tolist()],
            n_results=n,
            include=["distances"],
        )
        ids = result["ids"][0]
        distances = result["distances"][0]
        # Chroma отдаёт косинусную ДИСТАНЦИЮ (1 - cos). Возвращаем близость,
        # чтобы шкала совпадала с numpy-бэкендом и порогом retrieval.min_score.
        return [(cid, 1.0 - float(dist)) for cid, dist in zip(ids, distances)]

    def get_vectors(self, chunk_ids: Sequence[str]) -> np.ndarray:
        collection = self._get_collection()
        result = collection.get(ids=list(chunk_ids), include=["embeddings"])
        # Порядок в ответе Chroma не гарантирован — восстанавливаем по id.
        order = {cid: i for i, cid in enumerate(result["ids"])}
        embeddings = np.asarray(result["embeddings"], dtype=np.float32)
        return np.vstack([embeddings[order[cid]] for cid in chunk_ids])

    # ------------------------------------------------- инкрементальность

    def delete_document(self, doc_id: str) -> int:
        """Удаляет все чанки документа. BM25 после этого требует пересборки."""
        collection = self._get_collection()
        victims = [c.chunk_id for c in self.chunks if c.doc_id == doc_id]
        if not victims:
            return 0
        collection.delete(ids=victims)
        self.chunks = [c for c in self.chunks if c.doc_id != doc_id]
        self.bm25 = BM25Index().build([c.embed_text for c in self.chunks])
        self.manifest["n_chunks"] = len(self.chunks)
        self.manifest["documents"] = _document_summary(self.chunks)
        self._reindex_lookup()
        return len(victims)

    def upsert_document(self, chunks: list[Chunk], vectors: np.ndarray) -> None:
        """Добавляет или заменяет документ без переиндексации всего корпуса."""
        if not chunks:
            return
        self.delete_document(chunks[0].doc_id)
        collection = self._get_collection()
        collection.upsert(
            ids=[c.chunk_id for c in chunks],
            embeddings=[v.tolist() for v in vectors],
            documents=[c.embed_text for c in chunks],
            metadatas=[_to_metadata(c) for c in chunks],
        )
        self.chunks.extend(chunks)
        self.bm25 = BM25Index().build([c.embed_text for c in self.chunks])
        self.manifest["n_chunks"] = len(self.chunks)
        self.manifest["documents"] = _document_summary(self.chunks)
        self._reindex_lookup()

    def clear(self) -> None:
        try:
            self._get_client().delete_collection(self.cfg.collection)
        except Exception:
            pass
        self._collection = None
        self._client = None
        super().clear()


# ----------------------------------------------------------------- фабрика

def create_store(cfg: Config) -> BaseStore:
    """Пустое хранилище для индексации."""
    backend = cfg.store.backend.lower()
    if backend == "chroma":
        return ChromaStore(cfg.index_dir, cfg.store)
    if backend == "numpy":
        return NumpyStore(cfg.index_dir)
    raise ValueError(f"Неизвестный бэкенд хранилища: {cfg.store.backend}")


def open_store(cfg: Config) -> BaseStore:
    """Загружает существующий индекс, сверяя бэкенд с манифестом."""
    manifest_path = Path(cfg.index_dir) / MANIFEST
    if not manifest_path.exists():
        raise FileNotFoundError(
            f"Индекс не найден в {cfg.index_dir}. Сначала выполните: ragkb index"
        )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    indexed_backend = manifest.get("backend", "numpy")
    wanted = cfg.store.backend.lower()
    if indexed_backend != wanted:
        raise ValueError(
            f"Индекс построен бэкендом «{indexed_backend}», а конфиг требует «{wanted}». "
            f"Переиндексируйте базу (ragkb index --rebuild) или верните прежний бэкенд."
        )
    if indexed_backend == "chroma":
        return ChromaStore.load(cfg.index_dir, cfg.store)
    return NumpyStore.load(cfg.index_dir)


# ---------------------------------------------------------------- утилиты

_COLLECTION_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{1,510}[a-zA-Z0-9]$")


def _validate_collection_name(name: str) -> None:
    """Chroma отклоняет неподходящие имена невнятной ошибкой — проверим заранее."""
    if not _COLLECTION_RE.match(name):
        raise ValueError(
            f"Недопустимое имя коллекции «{name}»: нужно 3–512 символов из "
            f"[a-zA-Z0-9._-], начинается и заканчивается буквой или цифрой. "
            f"Исправьте store.collection в config.yaml."
        )

# Chroma принимает в метаданных только скаляры, поэтому вложенный dict
# сериализуем в строку, а None для страницы заменяем на -1.
def _to_metadata(chunk: Chunk) -> dict[str, Any]:
    return {
        "doc_id": chunk.doc_id,
        "text": chunk.text,
        "source": chunk.source,
        "title": chunk.title,
        "section": chunk.section,
        "page": chunk.page if chunk.page is not None else -1,
        "position": chunk.position,
        "format": str(chunk.meta.get("format", "")),
        "meta_json": json.dumps(chunk.meta, ensure_ascii=False),
    }


def _document_summary(chunks: Iterable[Chunk]) -> list[dict[str, Any]]:
    seen: dict[str, dict[str, Any]] = {}
    for chunk in chunks:
        entry = seen.setdefault(
            chunk.doc_id, {"title": chunk.title, "source": chunk.source, "chunks": 0}
        )
        entry["chunks"] += 1
    return list(seen.values())


# Обратная совместимость: раньше класс назывался VectorStore.
VectorStore = NumpyStore
