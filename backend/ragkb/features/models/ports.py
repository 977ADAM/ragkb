from __future__ import annotations

from typing import Protocol


class ModelCatalog(Protocol):
    def list(self) -> list: ...
    def resolve(self, requested: str | None) -> str: ...
