"""ragkb — локальная RAG-система над корпоративной базой знаний."""

from .config import Config
from .pipeline import (
    Answer,
    IndexReport,
    RAGPipeline,
    build_index,
    remove_document,
    update_documents,
)
from .retrieval import Hit
from .store import BaseStore, ChromaStore, NumpyStore, create_store, open_store

__version__ = "1.1.0"
__all__ = [
    "Config",
    "RAGPipeline",
    "build_index",
    "update_documents",
    "remove_document",
    "Answer",
    "IndexReport",
    "Hit",
    "BaseStore",
    "ChromaStore",
    "NumpyStore",
    "create_store",
    "open_store",
]
