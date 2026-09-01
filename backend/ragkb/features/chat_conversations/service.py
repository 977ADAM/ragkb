"""Сценарии диалогов и ответа."""
from __future__ import annotations

import json
import time
from collections.abc import AsyncIterator, Callable, Iterator
from typing import Any, Literal

from ragkb.core.config import LLMConfig
from ragkb.core.llm import ExtractiveLLM
from ragkb.core.pipeline import RAGPipeline
from ragkb.core.ports import AnswerEngine
from ragkb.core.prompts import ANSWER_TEMPLATE, SYSTEM_PROMPT, format_context
from ragkb.features.chat_conversations.cache import EventualCache
from ragkb.features.chat_conversations.ports import (
    AnswerHistory,
    ConversationRepository,
    SourceRegistry,
    make_title,
)
from ragkb.platform.auth import User
from ragkb.platform.errors import InvalidRequest, NotFound


class ChatConversationsService:
    def __init__(
        self,
        *,
        conversations: ConversationRepository,
        history: AnswerHistory,
        sources: SourceRegistry,
        engine: Callable[[], AnswerEngine],
        resolve_model: Callable[[str | None], str],
        require_org: Callable[[str], None],
        window: int,
        llm_cfg: LLMConfig,
    ):
        self.conversations = conversations
        self.history = history
        self.sources = sources
        self._engine = engine
        self.resolve_model = resolve_model
        self.require_org = require_org
        self.window = window
        self.llm_cfg = llm_cfg
        self.cache = EventualCache()

    async def create(self, user: User, organization_id: str) -> dict[str, str]:
        self.require_org(organization_id)
        cid = await self.history.create(user.name)
        return {"conversation_id": cid, "title": ""}

    async def list_page(
        self,
        user: User,
        organization_id: str,
        *,
        limit: int,
        offset: int,
        consistency: Literal["strong", "eventual"],
    ) -> dict[str, Any]:
        self.require_org(organization_id)
        key = (user.name, limit, offset)
        if consistency == "eventual":
            cached = self.cache.get(key)
            if cached is not None:
                return {
                    "organization_id": organization_id,
                    "consistency": consistency,
                    "cached": True,
                    **cached,
                }
        if consistency == "strong":
            await self.conversations.cleanup()
        payload = {
            "conversations": [
                c.to_dict()
                for c in await self.conversations.list_conversations(
                    user.name, limit=limit, offset=offset
                )
            ],
            "total": await self.conversations.count_conversations(user.name),
            "limit": limit,
            "offset": offset,
        }
        if consistency == "eventual":
            self.cache.set(key, payload)
        return {
            "organization_id": organization_id,
            "consistency": consistency,
            "cached": False,
            **payload,
        }

    async def get(self, user: User, organization_id: str, cid: str) -> dict[str, Any]:
        self.require_org(organization_id)
        messages = await self.conversations.get_messages(cid, user.name)
        if messages is None:
            raise NotFound("Диалог не найден")
        return {
            "id": cid,
            "messages": self._mark_availability([m.to_dict() for m in messages]),
        }

    async def rename(
        self, user: User, organization_id: str, cid: str, title: str
    ) -> dict[str, str]:
        self.require_org(organization_id)
        if not await self.conversations.rename(cid, user.name, title):
            raise NotFound("Диалог не найден")
        return {"id": cid, "title": title}

    async def delete(self, user: User, organization_id: str, cid: str) -> dict[str, bool]:
        self.require_org(organization_id)
        if not await self.conversations.delete(cid, user.name):
            raise NotFound("Диалог не найден")
        return {"deleted": True}

    async def stream_message(
        self,
        user: User,
        organization_id: str,
        cid: str,
        *,
        question: str,
        top_k: int | None,
        expand: bool,
        model: str | None,
    ) -> AsyncIterator[str]:
        self.require_org(organization_id)
        if not await self.history.owns(cid, user.name):
            raise NotFound("Диалог не найден")
        try:
            resolved = self.resolve_model(model)
        except ValueError as exc:
            raise InvalidRequest(str(exc)) from exc

        engine = self._engine()
        turns = await self.history.recent_turns(cid, user.name, self.window)
        try:
            await self.history.append(cid, user.name, "user", question)
            await self.history.set_title_if_empty(cid, user.name, make_title(question))
        except Exception:
            pass

        started = time.time()
        hits, tokens = engine.stream_answer(
            question, top_k=top_k, history=turns or None, expand=expand, model=resolved
        )
        return self._generate(
            tokens, hits, cid, user.name, question, resolved, started, engine
        )

    async def _generate(
        self,
        tokens: Iterator[str],
        hits,
        cid: str,
        user: str,
        question: str,
        model: str,
        started: float,
        engine: AnswerEngine,
    ) -> AsyncIterator[str]:
        collected: list[str] = []
        warnings: list[str] = []
        truncated = False
        try:
            for piece in tokens:
                collected.append(piece)
                yield json.dumps({"type": "token", "text": piece}, ensure_ascii=False) + "\n"
        except Exception as exc:
            if collected:
                truncated = True
                warnings.append("Ответ оборвался и сохранён неполностью")
            else:
                warnings.append(f"{exc} — ответ собран экстрактивно")
                prompt = ANSWER_TEMPLATE.format(
                    context=format_context(hits), question=question
                )
                fallback = ExtractiveLLM(self.llm_cfg).generate(SYSTEM_PROMPT, prompt)
                collected.append(fallback)
                yield json.dumps(
                    {"type": "token", "text": fallback}, ensure_ascii=False
                ) + "\n"

        text = "".join(collected)
        sources = RAGPipeline._cited_sources(text, hits)
        if not hits:
            warnings.append("Поиск не вернул ни одного релевантного фрагмента")
        if not sources and "нет информации" not in text.lower():
            warnings.append(
                "Модель не проставила ссылки на источники — ответ стоит проверить"
            )
        try:
            saved = await self.history.append(
                cid, user, "assistant", text, sources, model=model
            )
            if not saved:
                warnings.append("Ответ не сохранён в историю диалога")
        except Exception:
            warnings.append("Ответ не сохранён в историю диалога")

        yield json.dumps(
            {
                "type": "done",
                "conversation_id": cid,
                "sources": sources,
                "warnings": warnings,
                "elapsed_sec": round(time.time() - started, 2),
                "model": model,
                "truncated": truncated,
            },
            ensure_ascii=False,
        ) + "\n"

    def _mark_availability(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        paths = self.sources.document_paths()
        if paths is None:
            return messages
        for message in messages:
            for source in message.get("sources", []):
                source["available"] = source.get("source") in paths
        return messages
