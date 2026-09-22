"""События ответа и кандидаты на скачивание — типы без LangChain.

Ядро отдаёт наружу только эти структуры: прикладной слой превращает их в
NDJSON, а инструмент получает результат вызова обычным словарём, который
уходит в сообщение модели. Здесь нет ни pydantic, ни FastAPI, ни верхних
слоёв — только стандартная библиотека.
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Literal, TypedDict
from urllib.parse import quote

# Имя инструмента, которым модель прикладывает оригинал.
TOOL_GET_DOWNLOAD_LINK = "get_download_link"

# Код отказа инструмента: наружу не уходят ни файловые пути, ни причина.
TOOL_NOT_AVAILABLE = "not_available"

DOWNLOAD_URL_PREFIX = "/api/documents"


class ToolCandidate(TypedDict):
    """Документ, который модель может приложить к ответу.

    `download_allowed` — состояние на момент подготовки набора: закрытые
    документы тоже видны, чтобы модель не выдумывала ссылку на них. Пути здесь
    нет: кандидат описывает документ, а не место на диске.
    """

    document_id: str
    filename: str
    download_allowed: bool


# Результат вызова инструмента: поля вложения либо `error=not_available`.
ToolResult = dict[str, Any]

DownloadResolver = Callable[[str], Awaitable[ToolResult]]


@dataclass(frozen=True)
class AnswerEvent:
    """Событие ответа: порция текста, вложение или предупреждение."""

    kind: Literal["token", "attachment", "warning"]
    value: str | dict[str, Any]


def download_url(document_id: str) -> str:
    """Относительный адрес BFF: и хост, и путь выбирает сервер, а не модель."""
    return f"{DOWNLOAD_URL_PREFIX}/{quote(document_id, safe='')}/download"


def attachment_result(
    *, document_id: str, filename: str, media_type: str, size: int
) -> ToolResult:
    """Успешный результат инструмента: те же поля, что у вложения ответа."""
    return {
        "document_id": document_id,
        "filename": filename,
        "url": download_url(document_id),
        "media_type": media_type,
        "size": int(size),
    }


def not_available_result() -> ToolResult:
    """Отказ без путей и подробностей: модель не должна их пересказывать."""
    return {"error": TOOL_NOT_AVAILABLE}
