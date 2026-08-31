"""Схемы HTTP слайса диалогов."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from ragkb.features.chat_conversations.ports import TITLE_LIMIT


class RenameRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=TITLE_LIMIT)

    @field_validator("title")
    @classmethod
    def strip_and_require(cls, value: str) -> str:
        title = " ".join(value.split())
        if not title:
            raise ValueError("Заголовок не может быть пустым")
        return title


class MessageRequest(BaseModel):
    question: str = Field(..., min_length=2)
    top_k: int | None = Field(None, ge=1, le=20)
    expand: bool = False
    model: str | None = None


class OrgConversationsResponse(BaseModel):
    organization_id: str
    conversations: list[dict[str, Any]]
    total: int
    limit: int
    offset: int
    consistency: Literal["strong", "eventual"]
    cached: bool
