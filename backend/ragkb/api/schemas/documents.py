"""Схемы управления документами корпуса."""
from __future__ import annotations

from pydantic import BaseModel, Field


class AcceptRequest(BaseModel):
    """Принятие в корпус файлов, положенных в каталог мимо интерфейса."""

    names: list[str] = Field(default_factory=list)
