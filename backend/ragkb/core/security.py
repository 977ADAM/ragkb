"""Env-based admin credentials. No SQLAlchemy."""
from __future__ import annotations

import logging
import os
import re

_USERNAME = re.compile(r"^[a-z0-9._-]+$")


def get_admin_credentials() -> tuple[str, str] | None:
    login = os.environ.get("ADMIN_LOGIN", "").strip().lower()
    password = os.environ.get("ADMIN_PASSWORD", "")
    if not login or not password:
        logging.warning("ADMIN_LOGIN / ADMIN_PASSWORD empty; skipping admin seed")
        return None
    if not _USERNAME.fullmatch(login) or not (3 <= len(login) <= 32):
        logging.warning("ADMIN_LOGIN is not a valid username")
        return None
    if not (8 <= len(password) <= 128):
        logging.warning("ADMIN_PASSWORD length must be between 8 and 128")
        return None
    return (login, password)
