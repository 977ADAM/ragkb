"""Доменные ошибки прикладного слоя. Роутеры их не бросают."""
from __future__ import annotations

import logging

from fastapi import Request
from fastapi.responses import JSONResponse

log = logging.getLogger("ragkb")


class RagkbError(Exception):
    def __init__(self, detail: str):
        super().__init__(detail)
        self.detail = detail


class NotFound(RagkbError):
    pass


class Unauthenticated(RagkbError):
    pass


class Forbidden(RagkbError):
    pass


class InvalidRequest(RagkbError):
    pass


class Conflict(RagkbError):
    pass


class EngineUnavailable(RagkbError):
    pass


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
