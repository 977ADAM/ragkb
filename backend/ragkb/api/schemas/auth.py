"""Pydantic-схемы auth."""
from __future__ import annotations

import re
from datetime import datetime

from typing import ClassVar
from pydantic import BaseModel, Field, field_validator, ConfigDict

_USERNAME = re.compile(r"^[a-z0-9._-]+$")


class Credentials(BaseModel):
    username: str = Field(min_length=3, max_length=32)
    password: str = Field(min_length=8, max_length=128)

    @field_validator("username")
    @classmethod
    def normalize_username(cls, value: str) -> str:
        value = value.lower().strip()
        if not _USERNAME.fullmatch(value):
            raise ValueError("некорректный логин")
        if not (3 <= len(value) <= 32):
            raise ValueError("некорректный логин")
        return value



class UserRresponse(BaseModel):
    """Ответ с данными пользователя."""    
    id: int
    email: str
    username: str
    created_at: datetime

    model_config: ClassVar[ConfigDict] = ConfigDict(from_attributes=True)

class MessageResponse(BaseModel):
    """Ответ с сообщением."""
    message: str
