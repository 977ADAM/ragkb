"""Журнал изменений разрешения на выдачу оригинала.

Отдельной системы аудита нет: события идут в существующий журнал, а связать
строки BFF и backend можно по request_id. Личность при этом не устанавливается
— учётных записей в приложении нет, и метка запроса ею не становится.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import Request

log = logging.getLogger("ragkb")

REQUEST_ID_HEADER = "X-Request-Id"


def request_id(request: Request) -> str:
    """Метка запроса от доверенной стороны.

    Значение приходит от BFF: backend его не проверяет и доказательством
    личности не считает, а только переносит в журнал.
    """
    return request.headers.get(REQUEST_ID_HEADER, "").strip()[:64]


def log_permission_change(
    *,
    action: str,
    document_id: str,
    previous: bool,
    current: bool,
    request_id: str,
) -> None:
    """Пишется после успешного сохранения.

    Иначе запись выдавала бы желаемое за факт: неудачное изменение в журнале
    выглядело бы как состоявшееся.
    """
    log.info(
        "выдача оригинала: event=download_permission action=%s result=ok at=%s"
        " request_id=%s document_id=%s old=%s new=%s",
        action,
        datetime.now(timezone.utc).isoformat(timespec="seconds"),
        request_id or "-",
        document_id,
        _flag(previous),
        _flag(current),
    )


def _flag(value: bool) -> str:
    return "true" if value else "false"
