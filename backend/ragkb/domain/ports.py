"""Порты репозиториев и сервисов. Типизированы на domain.entities."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol

from ragkb.domain.entities import ORIGIN_UI, Conversation, CorpusDocument, Message

# --- Аккаунты ---


class AccountStore(Protocol):
    async def create_user(
        self, username: str, password_hash: str, role: str = "user"
    ) -> str: ...
    async def get_by_username(
        self, username: str
    ) -> tuple[str, str, str, str] | None: ...
    async def get_profile(self, username: str) -> tuple[str, str, datetime] | None:
        """(role, created_at) локального аккаунта."""
    async def update_password(self, username: str, password_hash: str) -> None: ...
    async def create_session(
        self, user_id: str, token_hash: str, expires_at: str
    ) -> None: ...
    async def delete_session(self, token_hash: str) -> None: ...
    async def delete_other_sessions(
        self, user_id: str, keep_token_hash: str
    ) -> None: ...
    async def user_for_token_hash(
        self, token_hash: str
    ) -> tuple[str, str, str] | None: ...
    async def list_users(self) -> list[tuple[str, str, datetime]]: ...
    async def set_role(
        self, username: str, role: str
    ) -> tuple[str, str, datetime] | None: ...
    async def delete_user(self, username: str) -> bool: ...
    async def count_admins(self) -> int: ...


# --- Диалоги ---


class ConversationRepository(Protocol):
    async def create(self, user: str) -> str: ...
    async def owns(self, conversation_id: str, user: str) -> bool: ...
    async def list_conversations(
        self, user: str, limit: int = 50, offset: int = 0
    ) -> list[Conversation]: ...
    async def count_conversations(self, user: str) -> int: ...
    async def get_messages(self, conversation_id: str, user: str) -> list[Message] | None: ...
    async def append(
        self,
        conversation_id: str,
        user: str,
        role: str,
        text: str,
        sources: list[dict[str, Any]] | None = None,
        model: str = "",
    ) -> int | None:
        """Сохраняет сообщение и возвращает его id (None — не сохранено)."""
    async def set_title_if_empty(self, conversation_id: str, user: str, title: str) -> bool: ...
    async def rename(self, conversation_id: str, user: str, title: str) -> bool: ...
    async def delete(self, conversation_id: str, user: str) -> bool: ...
    async def remove_message(self, message_id: int, user: str) -> bool:
        """Удаляет одно сообщение, если его диалог принадлежит пользователю."""
    async def cleanup(self, now=None, batch: int = 500) -> int: ...


class AnswerHistory(Protocol):
    async def owns(self, conversation_id: str, user: str) -> bool: ...
    async def recent_turns(
        self, conversation_id: str, user: str, window: int
    ) -> list[tuple[str, str]]: ...
    async def create(self, user: str) -> str: ...
    async def append(
        self,
        conversation_id: str,
        user: str,
        role: str,
        text: str,
        sources: list[dict[str, Any]] | None = None,
        model: str = "",
    ) -> int | None:
        """Сохраняет сообщение и возвращает его id (None — не сохранено)."""
    async def set_title_if_empty(self, conversation_id: str, user: str, title: str) -> bool: ...


class SourceRegistry(Protocol):
    def document_paths(self) -> set[str] | None: ...


# --- Документы корпуса ---


class DocumentRegistry(Protocol):
    """Реестр документов корпуса: что и кем принято в базу знаний.

    Индекс собирается по реестру, поэтому «нет записи» значит «файл лежит
    в каталоге мимо интерфейса и в ответы не попадёт», пока его не примут.
    """

    async def names(self) -> set[str]:
        """Имена (пути относительно каталога корпуса) принятых документов."""
    async def list_all(self) -> list[CorpusDocument]: ...
    async def record(
        self,
        name: str,
        *,
        origin: str = ORIGIN_UI,
        uploaded_by: str = "",
        size: int = 0,
        sha256: str = "",
    ) -> None:
        """Заводит документ или обновляет сведения о нём."""
    async def forget(self, name: str) -> bool:
        """Убирает документ из реестра. True — запись была."""


# --- Оценки ответов ---


class FeedbackStore(Protocol):
    async def conversation_owned_by(
        self, conversation_id: str, user: str
    ) -> bool: ...
    async def message_in_conversation(
        self, message_id: int, conversation_id: str
    ) -> bool: ...
    async def set_feedback(self, message_id: int, rating: str, comment: str) -> None:
        """Записывает или меняет оценку сообщения (одна на сообщение)."""
    async def counts(self) -> tuple[int, int]:
        """(up, down) по всем оценкам."""
    async def list_feedback(
        self, limit: int = 200
    ) -> list[tuple[str, str, str, str, str, str]]:
        """(conversation_id, username, rating, comment, answer, created_at)."""


# --- Модели ---


class ModelCatalog(Protocol):
    def list(self) -> list: ...
    def resolve(self, requested: str | None) -> str: ...


# --- Телеметрия ---


class EventSink(Protocol):
    def emit(self, payload: dict[str, Any]) -> None: ...
