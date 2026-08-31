"""История без файла: history.enabled = false."""
from __future__ import annotations

import uuid
from typing import Any

from ragkb.features.chat_conversations.ports import Conversation, Message


class EphemeralHistory:
    def create(self, user: str) -> str:
        return str(uuid.uuid4())

    def owns(self, conversation_id: str, user: str) -> bool:
        try:
            uuid.UUID(conversation_id)
        except ValueError:
            return False
        return True

    def list_conversations(
        self, user: str, limit: int = 50, offset: int = 0
    ) -> list[Conversation]:
        return []

    def count_conversations(self, user: str) -> int:
        return 0

    def get_messages(self, conversation_id: str, user: str) -> list[Message]:
        return []

    def append(
        self,
        conversation_id: str,
        user: str,
        role: str,
        text: str,
        sources: list[dict[str, Any]] | None = None,
        model: str = "",
    ) -> bool:
        return True

    def set_title_if_empty(self, conversation_id: str, user: str, title: str) -> bool:
        return True

    def rename(self, conversation_id: str, user: str, title: str) -> bool:
        return True

    def delete(self, conversation_id: str, user: str) -> bool:
        return True

    def cleanup(self, now=None, batch: int = 500) -> int:
        return 0

    def recent_turns(
        self, conversation_id: str, user: str, window: int
    ) -> list[tuple[str, str]]:
        return []
