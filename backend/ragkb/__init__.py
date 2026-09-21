"""ragkb — локальная RAG-система над корпоративной базой знаний."""

from ragkb.core.config import Settings
from ragkb.core.pipeline import IndexReport, RagChain, build_index, remove_document
from ragkb.core.retrieval import Hit
from ragkb.version import __version__

__all__ = [
    "Hit",
    "IndexReport",
    "RagChain",
    "Settings",
    "__version__",
    "build_index",
    "remove_document",
]
