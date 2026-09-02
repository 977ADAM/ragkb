from pydantic import BaseModel, Field


class FeedbackBody(BaseModel):
    """Тело оценки. Значения rating и длину comment проверяет сервис (400)."""

    rating: str = Field(...)
    comment: str = Field(default="")
