"""История диалогов и усыновление схемы."""
from __future__ import annotations

import inspect
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from helpers import alembic_sync_url, database_url, migrate
from sqlalchemy import create_engine, text

from ragkb.core.config import LLMConfig
from ragkb.features.chat_conversations.ephemeral import EphemeralHistory
from ragkb.features.chat_conversations.ports import make_title
from ragkb.features.chat_conversations.postgres import PostgresHistory
from ragkb.features.chat_conversations.service import ChatConversationsService
from ragkb.platform.auth import User
from ragkb.platform.db import EXPECTED_REVISION, make_engine, make_session_factory
from ragkb.platform.errors import NotFound


def test_make_title_trims():
    assert len(make_title("  " + "ж" * 80)) == 60


def test_stream_message_is_coroutine_not_async_generator():
    assert inspect.iscoroutinefunction(ChatConversationsService.stream_message)
    assert not inspect.isasyncgenfunction(ChatConversationsService.stream_message)


@pytest.mark.asyncio
async def test_stream_message_unknown_conversation_raises_before_iterator() -> None:
    history = MagicMock()
    history.owns = AsyncMock(return_value=False)
    svc = ChatConversationsService(
        conversations=MagicMock(),
        history=history,
        sources=MagicMock(),
        engine=lambda: MagicMock(),
        resolve_model=lambda model: "m",
        require_org=lambda _org: None,
        window=4,
        llm_cfg=LLMConfig(),
    )
    with pytest.raises(NotFound):
        await svc.stream_message(
            User(name="ada"),
            "acme",
            str(uuid4()),
            question="сколько дней отпуска?",
            top_k=None,
            expand=False,
            model=None,
        )


@pytest.mark.asyncio
async def test_postgres_crud() -> None:
    migrate()
    engine = make_engine(database_url())
    store = PostgresHistory(make_session_factory(engine))
    await store.ready()
    cid = await store.create("ada")
    assert await store.owns(cid, "ada")
    assert not await store.owns(cid, "bob")
    assert await store.append(cid, "ada", "user", "вопрос")
    assert await store.set_title_if_empty(cid, "ada", "вопрос")
    assert await store.get_messages(cid, "bob") is None
    msgs = await store.get_messages(cid, "ada")
    assert msgs and msgs[0].text == "вопрос"
    await engine.dispose()


@pytest.mark.asyncio
async def test_ephemeral_create_is_uuid():
    store = EphemeralHistory()
    cid = await store.create("x")
    assert await store.owns(cid, "anyone")
    assert await store.get_messages(cid, "x") == []


def test_alembic_fresh_db() -> None:
    migrate()
    engine = create_engine(alembic_sync_url(database_url()))
    with engine.connect() as conn:
        names = {
            r[0]
            for r in conn.execute(
                text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
            )
        }
        assert "conversations" in names
        assert "messages" in names
        rev = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
        assert rev == EXPECTED_REVISION
        model = conn.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'messages' AND column_name = 'model'"
            )
        ).scalar()
        assert model == "model"
