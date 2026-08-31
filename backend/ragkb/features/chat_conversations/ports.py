"""Порты слайса диалогов."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Protocol

TITLE_LIMIT = 60


def make_title(question: str) -> str:
    title = re.sub(r"\s+", " ", question).strip()
    return title[:TITLE_LIMIT] if len(title) > TITLE_LIMIT else title


@dataclass(frozen=True)
class Conversation:
    id: str
    title: str
    created_at: str
    updated_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


@dataclass(frozen=True)
class Message:
    role: str
    text: str
    created_at: str
    sources: list[dict[str, Any]] = field(default_factory=list)
    model: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "text": self.text,
            "created_at": self.created_at,
            "sources": self.sources,
            "model": self.model,
        }


class ConversationRepository(Protocol):
    def create(self, user: str) -> str: ...
    def owns(self, conversation_id: str, user: str) -> bool: ...
    def list_conversations(
        self, user: str, limit: int = 50, offset: int = 0
    ) -> list[Conversation]: ...
    def count_conversations(self, user: str) -> int: ...
    def get_messages(self, conversation_id: str, user: str) -> list[Message] | None: ...
    def append(
        self,
        conversation_id: str,
        user: str,
        role: str,
        text: str,
        sources: list[dict[str, Any]] | None = None,
        model: str = "",
    ) -> bool: ...
    def set_title_if_empty(self, conversation_id: str, user: str, title: str) -> bool: ...
    def rename(self, conversation_id: str, user: str, title: str) -> bool: ...
    def delete(self, conversation_id: str, user: str) -> bool: ...
    def cleanup(self, now=None, batch: int = 500) -> int: ...


class AnswerHistory(Protocol):
    def owns(self, conversation_id: str, user: str) -> bool: ...
    def recent_turns(
        self, conversation_id: str, user: str, window: int
    ) -> list[tuple[str, str]]: ...
    def create(self, user: str) -> str: ...
    def append(
        self,
        conversation_id: str,
        user: str,
        role: str,
        text: str,
        sources: list[dict[str, Any]] | None = None,
        model: str = "",
    ) -> bool: ...
    def set_title_if_empty(self, conversation_id: str, user: str, title: str) -> bool: ...


class SourceRegistry(Protocol):
    def document_paths(self) -> set[str] | None: ...
