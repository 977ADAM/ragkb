"""ragkb — локальная RAG-система над корпоративной базой знаний."""

from ragkb.core.config import Settings
from ragkb.core.pipeline import (
    Answer,
    IndexReport,
    RAGPipeline,
    build_index,
    remove_document,
    update_documents,
)
from ragkb.core.retrieval import Hit
from ragkb.core.store import BaseStore, ChromaStore, NumpyStore, create_store, open_store
from ragkb.version import __version__

__all__ = [
    "Answer",
    "BaseStore",
    "ChromaStore",
    "Hit",
    "IndexReport",
    "NumpyStore",
    "RAGPipeline",
    "Settings",
    "__version__",
    "build_index",
    "create_store",
    "open_store",
    "remove_document",
    "update_documents",
]
