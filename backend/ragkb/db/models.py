"""ORM-модели auth. Схемой владеет Alembic."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Text, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from ragkb.core.database import Base
from ragkb.domain.entities import Session, User


class UserRow(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True)
    username: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=func.now()
    )

    def to_domain(self) -> User:
        return User(
            id=self.id,
            username=self.username,
            password_hash=self.password_hash,
            created_at=self.created_at,
        )

    @classmethod
    def from_domain(cls, user: User) -> UserRow:
        return cls(
            id=user.id,
            username=user.username,
            password_hash=user.password_hash,
            created_at=user.created_at,
        )


class SessionRow(Base):
    __tablename__ = "sessions"

    token_hash: Mapped[str] = mapped_column(Text, primary_key=True)
    user_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    def to_domain(self) -> Session:
        return Session(
            token_hash=self.token_hash,
            user_id=self.user_id,
            expires_at=self.expires_at,
        )

    @classmethod
    def from_domain(cls, session: Session) -> SessionRow:
        return cls(
            token_hash=session.token_hash,
            user_id=session.user_id,
            expires_at=session.expires_at,
        )
