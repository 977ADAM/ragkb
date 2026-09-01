from __future__ import annotations

from datetime import datetime, timezone

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

COOKIE_NAME = "ragkb_session"
SESSION_DAYS = 7


def utcnow() -> datetime:
    return datetime.now(timezone.utc)

_hasher = PasswordHasher()


def hash_password(plain: str) -> str:
    return _hasher.hash(plain)


def verify_password(plain: str, password_hash: str) -> bool:
    try:
        return _hasher.verify(password_hash, plain)
    except (VerifyMismatchError, InvalidHashError):
        return False
