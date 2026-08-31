from __future__ import annotations

from collections.abc import Callable

from pydantic import BaseModel, Field

from ragkb.core.ports import AnswerEngine


class SearchRequest(BaseModel):
    query: str = Field(..., min_length=2)
    top_k: int = 5


class SearchService:
    def __init__(self, get_engine: Callable[[], AnswerEngine]):
        self._engine = get_engine

    def search(self, query: str, top_k: int) -> dict:
        hits = self._engine().search(query, top_k=top_k)
        return {"query": query, "results": [h.to_dict() for h in hits]}
