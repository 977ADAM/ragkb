"""DTO выдачи оригинала: изменение разрешения и вложение ответа."""
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class DownloadPermissionUpdate(BaseModel):
    """Тело PATCH: значение задаётся явно, лишние поля отклоняются."""

    model_config = ConfigDict(extra="forbid", strict=True)

    download_allowed: bool


class DownloadPermissionResponse(BaseModel):
    document_id: UUID
    download_allowed: bool


class Attachment(BaseModel):
    """Файл, приложенный к ответу чата.

    Карточку интерфейс строит по этому описанию, а не по ссылкам в тексте
    модели. `url` — относительный адрес BFF, поэтому файловых путей здесь нет.
    """

    document_id: UUID
    filename: str
    url: str
    media_type: str
    size: int = Field(ge=0)
