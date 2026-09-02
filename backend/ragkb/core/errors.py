"""Доменные ошибки прикладного слоя. Роутеры их не бросают.

Чистый модуль без FastAPI: статус-коды и HTTP-хендлер живут в api/errors.py.
"""
from __future__ import annotations


class RagkbError(Exception):
    def __init__(self, detail: str):
        super().__init__(detail)
        self.detail = detail


class NotFound(RagkbError):
    pass


class Unauthenticated(RagkbError):
    pass


class Forbidden(RagkbError):
    pass


class InvalidRequest(RagkbError):
    pass


class Conflict(RagkbError):
    pass


class EngineUnavailable(RagkbError):
    pass
