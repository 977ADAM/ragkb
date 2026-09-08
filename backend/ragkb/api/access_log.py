"""Access-лог без буферизации потоковых ответов."""
from __future__ import annotations

import time

from ragkb.core.logging_config import get_logger

log = get_logger("ragkb")


class AccessLogMiddleware:
    """Метод, путь, статус, длительность, пользователь.

    Чистый ASGI, а не BaseHTTPMiddleware: не буферизует NDJSON генерации.
    Пользователь берётся из scope.state — его кладут Depends(current_user),
    поэтому он виден только на защищённых роутах.
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
            user = ""
            state = scope.get("state") or {}
            current = state.get("user")
            if current is not None:
                user = getattr(current, "name", "")
            log.info(
                "%s %s -> %d (%.0f ms)%s",
                scope.get("method", ""),
                scope.get("path", ""),
                status["code"],
                elapsed_ms,
                f" user={user}" if user else "",
            )
