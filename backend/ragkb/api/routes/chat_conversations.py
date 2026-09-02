"""HTTP диалогов."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse

from ragkb.api.deps.auth import current_user
from ragkb.api.deps.services import chat_conversations_service, feedback_service
from ragkb.api.schemas.chat_conversations import (
    MessageRequest,
    OrgConversationsResponse,
    RenameRequest,
)
from ragkb.api.schemas.feedback import FeedbackBody
from ragkb.domain.entities import User
from ragkb.services.chat_conversations import ChatConversationsService
from ragkb.services.feedback import FeedbackService

router = APIRouter()


@router.get(
    "/organization/{organization_id}/chat_conversations",
    response_model=OrgConversationsResponse,
)
async def list_conversations(
    organization_id: str,
    user: User = Depends(current_user),
    svc: ChatConversationsService = Depends(chat_conversations_service),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    consistency: Literal["strong", "eventual"] = "strong",
) -> OrgConversationsResponse:
    return OrgConversationsResponse(
        **await svc.list_page(
            user, organization_id, limit=limit, offset=offset, consistency=consistency
        )
    )


@router.post("/organization/{organization_id}/chat_conversations")
async def create_conversation(
    organization_id: str,
    user: User = Depends(current_user),
    svc: ChatConversationsService = Depends(chat_conversations_service),
) -> dict[str, str]:
    return await svc.create(user, organization_id)


@router.get("/organization/{organization_id}/chat_conversations/{cid}")
async def get_conversation(
    organization_id: str,
    cid: str,
    user: User = Depends(current_user),
    svc: ChatConversationsService = Depends(chat_conversations_service),
) -> dict:
    return await svc.get(user, organization_id, cid)


@router.patch("/organization/{organization_id}/chat_conversations/{cid}")
async def rename_conversation(
    organization_id: str,
    cid: str,
    req: RenameRequest,
    user: User = Depends(current_user),
    svc: ChatConversationsService = Depends(chat_conversations_service),
) -> dict[str, str]:
    return await svc.rename(user, organization_id, cid, req.title)


@router.delete("/organization/{organization_id}/chat_conversations/{cid}")
async def delete_conversation(
    organization_id: str,
    cid: str,
    user: User = Depends(current_user),
    svc: ChatConversationsService = Depends(chat_conversations_service),
) -> dict[str, bool]:
    return await svc.delete(user, organization_id, cid)


@router.patch(
    "/organization/{organization_id}/chat_conversations/{cid}/messages/{message_id}/feedback",
    status_code=204,
)
async def rate_message(
    organization_id: str,
    cid: str,
    message_id: int,
    body: FeedbackBody,
    user: User = Depends(current_user),
    svc: FeedbackService = Depends(feedback_service),
) -> None:
    await svc.rate(user.name, cid, message_id, body.rating, body.comment)


@router.post("/organization/{organization_id}/chat_conversations/{cid}/messages")
async def post_message(
    organization_id: str,
    cid: str,
    req: MessageRequest,
    user: User = Depends(current_user),
    svc: ChatConversationsService = Depends(chat_conversations_service),
) -> StreamingResponse:
    stream = await svc.stream_message(
        user,
        organization_id,
        cid,
        question=req.question,
        top_k=req.top_k,
        expand=req.expand,
        model=req.model,
    )
    return StreamingResponse(stream, media_type="application/x-ndjson; charset=utf-8")
