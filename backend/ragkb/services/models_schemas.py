from pydantic import BaseModel


class ModelInfo(BaseModel):
    id: str
    display_name: str | None = None
    context_window: int | None = None
    supports_tools: bool = False
    is_default: bool = False
