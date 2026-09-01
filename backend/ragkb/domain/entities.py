"""Доменные сущности. Чистые dataclass — без SQLAlchemy/pydantic."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass
class User:
    id: str
    username: str
    password_hash: str
    created_at: datetime | None = None


@dataclass
class Session:
    token_hash: str
    user_id: str
    expires_at: datetime
