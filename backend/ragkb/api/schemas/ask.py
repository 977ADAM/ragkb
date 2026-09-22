"""Параметры независимого вопроса и события его потока."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from ragkb.api.schemas.downloads import Attachment


class AskRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    question: str = Field(min_length=2)
    top_k: int | None = Field(None, ge=1, le=20)
    expand: bool = False
    model: str | None = None


class TokenEvent(BaseModel):
    """Строка потока с очередной порцией текста ответа."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["token"] = "token"
    text: str


class DoneEvent(BaseModel):
    """Последняя строка потока: источники, предупреждения и вложения.

    Вложения приходят отдельно от текста: карточку файла строит интерфейс по
    этому описанию, а не по ссылкам, которые модель написала словами.
    """

    model_config = ConfigDict(extra="forbid")

    type: Literal["done"] = "done"
    sources: list[dict] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    elapsed_sec: float = 0.0
    model: str = ""
    truncated: bool = False
    attachments: list[Attachment] = Field(default_factory=list)
