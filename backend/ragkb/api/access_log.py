"""Access-лог без буферизации потоковых ответов."""
from __future__ import annotations

import time

from ragkb.core.logging_config import get_logger

log = get_logger("ragkb")


class AccessLogMiddleware:
    """Метод, путь, статус, длительность.

    Чистый ASGI, а не BaseHTTPMiddleware: не буферизует NDJSON генерации.
    Личности в журнале нет — аккаунтов в приложении тоже нет.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        started = time.perf_counter()
        status = {"code": 500}

        async def _send(message):
            if message["type"] == "http.response.start":
                status["code"] = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, _send)
        finally:
            elapsed_ms = (time.perf_counter() - started) * 1000
            log.info(
                "%s %s -> %d (%.0f ms)",
                scope.get("method", ""),
                scope.get("path", ""),
                status["code"],
                elapsed_ms,
            )
