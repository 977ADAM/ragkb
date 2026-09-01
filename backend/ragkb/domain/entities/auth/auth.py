from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
import uuid


@dataclass
class User:
    """Пользователь системы."""
    id: int | None
    username: str
    email: str | None = None
    password_hash: str | None = None  # Храним только хеш!
    is_active: bool = True
    is_superuser: bool = False
    created_at: datetime | None = None
    updated_at: datetime | None = None
    
    @classmethod
    def create(cls, username: str, password_hash: str, email: str | None = None) -> User:
        """Фабричный метод для создания нового пользователя."""
        return cls(
            id=None,
            username=username,
            email=email,
            password_hash=password_hash,
            is_active=True,
            is_superuser=False,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )


@dataclass
class Session:
    """Сессия пользователя (для cookie-based auth)."""
    id: str  # UUID token
    user_id: int
    created_at: datetime
    expires_at: datetime
    user_agent: str | None = None
    ip_address: str | None = None
    
    @classmethod
    def create(cls, user_id: int, expires_in_days: int = 7) -> Session:
        """Создать новую сессию."""
        now = datetime.utcnow()
        return cls(
            id=str(uuid.uuid4()),
            user_id=user_id,
            created_at=now,
            expires_at=now + timedelta(days=expires_in_days)
        )
    
    def is_expired(self) -> bool:
        """Проверить, истекла ли сессия."""
        return datetime.utcnow() > self.expires_at