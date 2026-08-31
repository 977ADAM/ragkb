"""ragkb — локальная RAG-система над корпоративной базой знаний."""

from ragkb.core.config import Config
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

__version__ = "1.1.0"
__all__ = [
    "Answer",
    "BaseStore",
    "ChromaStore",
    "Config",
    "Hit",
    "IndexReport",
    "NumpyStore",
    "RAGPipeline",
    "build_index",
    "create_store",
    "open_store",
    "remove_document",
    "update_documents",
]
