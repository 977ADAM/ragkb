"""ORM-модели. Схемой владеет Alembic."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, BigInteger, DateTime, ForeignKey, Integer, Text, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from ragkb.core.database import Base
from ragkb.domain.entities import Account, Session


class UserRow(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True)
    username: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=func.now()
    )
    role: Mapped[str] = mapped_column(
        Text, nullable=False, default="user", server_default="user"
    )

    def to_domain(self) -> Account:
        return Account(
            id=self.id,
            username=self.username,
            password_hash=self.password_hash,
            created_at=self.created_at,
            role=self.role,
        )

    @classmethod
    def from_domain(cls, account: Account) -> UserRow:
        return cls(
            id=account.id,
            username=account.username,
            password_hash=account.password_hash,
            created_at=account.created_at,
            role=account.role,
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


class ConversationRow(Base):
    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True)
    owner: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=func.now()
    )


class MessageRow(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    conversation_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
    )
    role: Mapped[str] = mapped_column(Text, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    sources: Mapped[Any] = mapped_column(
        JSON, nullable=False, server_default="[]"
    )
    model: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=func.now()
    )


class MessageFeedbackRow(Base):
    __tablename__ = "message_feedback"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    message_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("messages.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    rating: Mapped[str] = mapped_column(Text, nullable=False)
    comment: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=func.now()
    )


class CleanupStateRow(Base):
    __tablename__ = "cleanup_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    last_run: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
