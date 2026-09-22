"""FastAPI-хендлер доменных ошибок ragkb. Классы — в core/errors.py."""
from __future__ import annotations

import logging

from fastapi import Request
from fastapi.responses import JSONResponse

from ragkb.core.errors import (
    Conflict,
    EngineUnavailable,
    InvalidRequest,
    NotFound,
    PayloadTooLarge,
    RagkbError,
)

log = logging.getLogger("ragkb")

_STATUS = {
    NotFound: 404,
    InvalidRequest: 400,
    PayloadTooLarge: 413,
    Conflict: 409,
    EngineUnavailable: 503,
}


def status_for(exc: RagkbError) -> int:
    """HTTP-статус доменной ошибки: один источник правды с хендлером.

    Нужен там, где ответ собирается на месте — например, чтобы добавить к
    отказу выдачи оригинала `Cache-Control: no-store`.
    """
    return _STATUS.get(type(exc), 500)


async def ragkb_error_handler(request: Request, exc: RagkbError) -> JSONResponse:
    status = status_for(exc)
    if status >= 500:
        log.exception("%s %s: %s", request.method, request.url.path, exc.detail)
    else:
        log.info("%s %s: %s", request.method, request.url.path, exc.detail)
    return JSONResponse({"detail": exc.detail}, status_code=status)


async def unhandled_exception(request: Request, exc: Exception) -> JSONResponse:
    log.exception("необработанная ошибка %s %s", request.method, request.url.path)
    return JSONResponse({"detail": "Внутренняя ошибка сервера"}, status_code=500)
