"""Pydantic-схемы auth."""
from __future__ import annotations

import re

from pydantic import BaseModel, Field, field_validator

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


class ChangePassword(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)

    @field_validator("new_password")
    @classmethod
    def require_length(cls, value: str) -> str:
        if not (8 <= len(value) <= 128):
            raise ValueError("пароль должен быть от 8 до 128 символов")
        return value
