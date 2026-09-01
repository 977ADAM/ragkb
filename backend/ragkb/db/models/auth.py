from __future__ import annotations

from datetime import datetime
from sqlalchemy import String, DateTime, Boolean
from sqlalchemy.orm import Mapped, mapped_column

from ragkb.core.database import Base


class UserRow(Base):
    __tablename__ = "users"
    
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    username: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_superuser: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    
    def to_domain(self) -> User:
        """Преобразовать ORM модель в доменную сущность."""
        return User(
            id=self.id,
            username=self.username,
            password_hash=self.password_hash,
            is_active=self.is_active,
            is_superuser=self.is_superuser,
            created_at=self.created_at,
            updated_at=self.updated_at
        )
    
    @classmethod
    def from_domain(cls, user: User) -> UserRow:
        """Создать ORM модель из доменной сущности."""
        return cls(
            id=user.id,
            username=user.username,
            password_hash=user.password_hash,
            is_active=user.is_active,
            is_superuser=user.is_superuser,
            created_at=user.created_at,
            updated_at=user.updated_at
        )


class SessionRow(Base):
    __tablename__ = "sessions"
    
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    
    def to_domain(self) -> Session:
        """Преобразовать ORM модель в доменную сущность."""
        return Session(
            token_hash=self.token_hash,
            user_id=self.user_id,
            created_at=self.created_at,
            expires_at=self.expires_at
        )
    
    @classmethod
    def from_domain(cls, session: Session) -> SessionRow:
        """Создать ORM модель из доменной сущности."""
        return cls(
            token_hash=session.token_hash,
            user_id=session.user_id,
            created_at=session.created_at,
            expires_at=session.expires_at
        )