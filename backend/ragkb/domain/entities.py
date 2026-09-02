"""Доменные сущности. Чистые dataclass — без SQLAlchemy/pydantic."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

# --- Утилиты заголовков диалогов ---

TITLE_LIMIT = 60


def make_title(question: str) -> str:
    title = re.sub(r"\s+", " ", question).strip()
    return title[:TITLE_LIMIT] if len(title) > TITLE_LIMIT else title


# --- Аккаунты и сессии ---


@dataclass
class Account:
    id: str
    username: str
    password_hash: str
    created_at: datetime | None = None
    role: str = "user"


@dataclass
class Session:
    token_hash: str
    user_id: str
    expires_at: datetime


# --- Личность запроса ---

ANONYMOUS = "anonymous"


@dataclass(frozen=True)
class User:
    name: str
    email: str = ""
    groups: tuple[str, ...] = ()
    role: str = "user"

    def in_group(self, group: str) -> bool:
        return group in self.groups


# --- Диалоги ---


# --- Оценки ответов ---

RATING_UP = "up"
RATING_DOWN = "down"
FEEDBACK_COMMENT_LIMIT = 500
FEEDBACK_ANSWER_SNIPPET = 200


@dataclass(frozen=True)
class Feedback:
    id: int
    message_id: int
    rating: str
    comment: str
    created_at: str
    updated_at: str


# --- Диалоги ---


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
    id: int | None = None

    def to_dict(self) -> dict[str, Any]:
        out = {
            "role": self.role,
            "text": self.text,
            "created_at": self.created_at,
            "sources": self.sources,
            "model": self.model,
        }
        if self.id is not None:
            out["id"] = self.id
        return out
