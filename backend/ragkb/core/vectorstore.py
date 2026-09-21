"""Векторное хранилище LangChain: langchain-chroma в работе, память в тестах.

Своей реализации хранилища у сервиса больше нет: `langchain-chroma` даёт
персистентный клиент, коллекцию с косинусной метрикой и обычные ретриверы,
а `InMemoryVectorStore` из langchain-core — тот же интерфейс без диска, чтобы
тесты не зависели от chromadb.

Манифест индекса (`core/manifest.py`) остаётся: по нему `/health`, `/status`
и страница документов понимают, собран ли индекс и чем именно.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_core.vectorstores import InMemoryVectorStore, VectorStore

from .config import Settings
from .documents import documents_from_payload
from .errors import EngineUnavailable

CHROMA_SUBDIR = "chroma"

# In-memory хранилища живут в процессе: сборка индекса и открытие движка —
# это два разных вызова, и второй должен увидеть то, что записал первый.
_MEMORY_STORES: dict[str, InMemoryVectorStore] = {}


def build_store(cfg: Settings, embeddings: Embeddings) -> VectorStore:
    """Пустое хранилище для полной переиндексации."""
    backend = cfg.store.backend.lower()
    if backend == "memory":
        memory = InMemoryVectorStore(embedding=embeddings)
        _MEMORY_STORES[_memory_key(cfg)] = memory
        return memory
    if backend != "chroma":
        raise EngineUnavailable(
            f"Неизвестный бэкенд хранилища «{cfg.store.backend}»: доступны chroma и memory"
        )
    store = _chroma(cfg, embeddings)
    # Полная сборка начинается с чистого листа: иначе чанки удалённых
    # документов остались бы в коллекции и находились в выдаче.
    reset = getattr(store, "reset_collection", None)
    if reset is not None:
        reset()
    return store


def open_store(cfg: Settings, embeddings: Embeddings) -> VectorStore:
    """Хранилище с уже собранным индексом."""
    if cfg.store.backend.lower() == "memory":
        store = _MEMORY_STORES.get(_memory_key(cfg))
        if store is None:
            raise EngineUnavailable(
                "Индекс в памяти не найден: он живёт только внутри процесса, "
                "который его собрал"
            )
        return store
    return _chroma(cfg, embeddings)


def _chroma(cfg: Settings, embeddings: Embeddings) -> VectorStore:
    from langchain_chroma import Chroma

    if cfg.store.chroma_host:
        return Chroma(
            collection_name=cfg.store.collection,
            embedding_function=embeddings,
            host=cfg.store.chroma_host,
            port=cfg.store.chroma_port,
            collection_metadata=_collection_metadata(cfg),
        )
    return Chroma(
        collection_name=cfg.store.collection,
        embedding_function=embeddings,
        persist_directory=str(Path(cfg.index_dir) / CHROMA_SUBDIR),
        collection_metadata=_collection_metadata(cfg),
    )


def _collection_metadata(cfg: Settings) -> dict[str, object]:
    # Косинус, а не L2 по умолчанию: векторы эмбеддера нормированы, и близость
    # согласуется с порогом retrieval.min_score.
    return {
        "hnsw:space": "cosine",
        "hnsw:construction_ef": cfg.store.hnsw_construction_ef,
        "hnsw:search_ef": cfg.store.hnsw_search_ef,
        "hnsw:M": cfg.store.hnsw_m,
    }


def _memory_key(cfg: Settings) -> str:
    return f"{cfg.store.collection}:{cfg.index_dir}"


def all_documents(store: VectorStore) -> list[Document]:
    """Все документы индекса: их читает BM25-половина гибридного поиска."""
    if isinstance(store, InMemoryVectorStore):
        # У хранилища в памяти нет get(): записи лежат словарём id → запись.
        return [
            Document(
                page_content=str(entry.get("text") or ""),
                metadata=_with_chunk_id(chunk_id, entry.get("metadata") or {}),
            )
            for chunk_id, entry in store.store.items()
        ]
    payload = _chroma_get(store, include=["documents", "metadatas"])
    return documents_from_payload(
        payload.get("documents") or [],
        payload.get("metadatas") or [],
        payload.get("ids") or [],
    )


def _with_chunk_id(chunk_id: str, metadata: dict[str, Any]) -> dict[str, Any]:
    """chunk_id из метаданных важнее идентификатора хранилища.

    При записи мы передаём свой chunk_id как id документа, но хранилище
    вправе выдать собственный; ссылки в ответе строятся по metadata.
    """
    return {**metadata, "chunk_id": str(metadata.get("chunk_id") or chunk_id)}


def _chroma_get(store: VectorStore, **kwargs: Any) -> dict[str, Any]:
    """`get()` есть у Chroma, но не в базовом интерфейсе VectorStore.

    Проверка типа здесь честнее, чем `# type: ignore`: если хранилище
    подменили на такое, что не умеет `get`, лучше явная ошибка.
    """
    getter = getattr(store, "get", None)
    if getter is None:
        raise EngineUnavailable(
            f"Хранилище {type(store).__name__} не умеет читать документы списком"
        )
    return dict(getter(**kwargs))


def vectors_for(store: VectorStore, chunk_ids: list[str]) -> dict[str, list[float]]:
    """Векторы чанков по идентификаторам — для оценки близости без повторного поиска."""
    if not chunk_ids:
        return {}
    if isinstance(store, InMemoryVectorStore):
        out: dict[str, list[float]] = {}
        for chunk_id, entry in store.store.items():
            vector = entry.get("vector")
            if vector is None:
                continue
            metadata = entry.get("metadata") or {}
            out[str(metadata.get("chunk_id") or chunk_id)] = [float(value) for value in vector]
        return out
    payload = _chroma_get(store, ids=chunk_ids, include=["embeddings"])
    embeddings = payload.get("embeddings")
    ids = payload.get("ids") or []
    if embeddings is None:
        return {}
    return {
        str(chunk_id): [float(value) for value in vector]
        for chunk_id, vector in zip(ids, embeddings, strict=False)
    }


def document_count(store: VectorStore) -> int:
    return len(all_documents(store))


def delete_by_source(store: VectorStore, source: str) -> int:
    """Удаляет чанки документа по исходному пути. Возвращает их число."""
    if isinstance(store, InMemoryVectorStore):
        victims = [
            chunk_id
            for chunk_id, entry in store.store.items()
            if str((entry.get("metadata") or {}).get("source") or "") == source
        ]
    else:
        payload = _chroma_get(store, where={"source": source})
        victims = list(payload.get("ids") or [])
    if victims:
        store.delete(victims)
    return len(victims)
