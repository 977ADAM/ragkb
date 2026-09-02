"""История без файла: history.enabled = false."""
from __future__ import annotations

import uuid
from typing import Any

from ragkb.domain.entities import Conversation, Message


class EphemeralHistory:
    async def create(self, user: str) -> str:
        return str(uuid.uuid4())

    async def owns(self, conversation_id: str, user: str) -> bool:
        try:
            uuid.UUID(conversation_id)
        except ValueError:
            return False
        return True

    async def list_conversations(
        self, user: str, limit: int = 50, offset: int = 0
    ) -> list[Conversation]:
        return []

    async def count_conversations(self, user: str) -> int:
        return 0

    async def get_messages(self, conversation_id: str, user: str) -> list[Message]:
        return []

    async def append(
        self,
        conversation_id: str,
        user: str,
        role: str,
        text: str,
        sources: list[dict[str, Any]] | None = None,
        model: str = "",
    ) -> int | None:
        # История выключена: сообщения нигде не хранятся, оценивать нечего.
        return None

    async def set_title_if_empty(self, conversation_id: str, user: str, title: str) -> bool:
        return True

    async def rename(self, conversation_id: str, user: str, title: str) -> bool:
        return True

    async def delete(self, conversation_id: str, user: str) -> bool:
        return True

    async def remove_message(self, message_id: int, user: str) -> bool:
        # Эфемерная история ничего не хранит — удалять нечего.
        return False

    async def cleanup(self, now=None, batch: int = 500) -> int:
        return 0

    async def recent_turns(
        self, conversation_id: str, user: str, window: int
    ) -> list[tuple[str, str]]:
        return []
