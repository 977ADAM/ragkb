from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from ragkb.api.deps.services import ask_service
from ragkb.api.schemas.ask import AskRequest
from ragkb.services.ask import AskService

router = APIRouter()


@router.post("/ask")
async def ask(req: AskRequest, svc: AskService = Depends(ask_service)) -> StreamingResponse:
    # Подготовка выполняется до открытия потока: отказ (400/503) должен быть
    # HTTP-ответом, а не первой строкой NDJSON.
    stream = await svc.stream(**req.model_dump())
    return StreamingResponse(stream, media_type="application/x-ndjson; charset=utf-8")
