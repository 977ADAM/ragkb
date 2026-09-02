"""Оценки ответов: правило владения и UPSERT."""
from __future__ import annotations

from ragkb.core.errors import InvalidRequest, NotFound
from ragkb.domain.entities import (
    FEEDBACK_ANSWER_SNIPPET,
    FEEDBACK_COMMENT_LIMIT,
    RATING_DOWN,
    RATING_UP,
)
from ragkb.domain.ports import FeedbackStore

_RATINGS = frozenset({RATING_UP, RATING_DOWN})


class FeedbackService:
    def __init__(self, store: FeedbackStore) -> None:
        self._store = store

    async def rate(
        self, user: str, conversation_id: str, message_id: int, rating: str, comment: str
    ) -> None:
        if rating not in _RATINGS:
            raise InvalidRequest("оценка только up или down")
        comment = (comment or "").strip()
        if len(comment) > FEEDBACK_COMMENT_LIMIT:
            raise InvalidRequest(
                f"Комментарий длиннее {FEEDBACK_COMMENT_LIMIT} символов"
            )
        if not await self._store.conversation_owned_by(conversation_id, user):
            raise NotFound("Диалог не найден")
        if not await self._store.message_in_conversation(message_id, conversation_id):
            raise NotFound("Сообщение не найдено")
        await self._store.set_feedback(message_id, rating, comment)

    async def summary(self, limit: int = 200) -> dict:
        up, down = await self._store.counts()
        items = []
        for conversation_id, username, rating, comment, answer, created_at in (
            await self._store.list_feedback(limit)
        ):
            snippet = answer.strip().replace("\n", " ")
            if len(snippet) > FEEDBACK_ANSWER_SNIPPET:
                snippet = snippet[:FEEDBACK_ANSWER_SNIPPET] + "…"
            items.append(
                {
                    "conversation_id": conversation_id,
                    "username": username,
                    "rating": rating,
                    "comment": comment,
                    "answer": snippet,
                    "created_at": created_at,
                }
            )
        return {"counts": {"up": up, "down": down}, "items": items}
