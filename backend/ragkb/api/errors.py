"""FastAPI-хендлер доменных ошибок ragkb. Классы — в core/errors.py."""
from __future__ import annotations

import logging

from fastapi import Request
from fastapi.responses import JSONResponse

from ragkb.core.errors import (
    Conflict,
    EngineUnavailable,
    Forbidden,
    InvalidRequest,
    NotFound,
    RagkbError,
    Unauthenticated,
)

log = logging.getLogger("ragkb")

_STATUS = {
    NotFound: 404,
    Unauthenticated: 401,
    Forbidden: 403,
    InvalidRequest: 400,
    Conflict: 409,
    EngineUnavailable: 503,
}


async def ragkb_error_handler(request: Request, exc: RagkbError) -> JSONResponse:
    status = _STATUS.get(type(exc), 500)
    if status >= 500:
        log.exception("%s %s: %s", request.method, request.url.path, exc.detail)
    else:
        log.info("%s %s: %s", request.method, request.url.path, exc.detail)
    return JSONResponse({"detail": exc.detail}, status_code=status)
