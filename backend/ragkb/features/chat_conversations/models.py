from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, BigInteger, DateTime, ForeignKey, Integer, Text, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from ragkb.platform.db import Base


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


class CleanupStateRow(Base):
    __tablename__ = "cleanup_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    last_run: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
