"""Параметры независимого вопроса."""
from pydantic import BaseModel, ConfigDict, Field


class AskRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    question: str = Field(min_length=2)
    top_k: int | None = Field(None, ge=1, le=20)
    expand: bool = False
    model: str | None = None
