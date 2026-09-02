"""Seed or refresh the admin account from ADMIN_LOGIN / ADMIN_PASSWORD."""
from __future__ import annotations

import asyncio
import logging
import sys
from datetime import datetime, timezone

from ragkb.core.config import DEFAULT_CONFIG, Config
from ragkb.core.database import make_engine, make_session_factory
from ragkb.core.security import get_admin_credentials
from ragkb.db.repos.auth import PostgresAccounts
from ragkb.domain.ports import AccountStore
from ragkb.services.auth import hash_password, verify_password


async def ensure_admin(store: AccountStore) -> None:
    creds = get_admin_credentials()
    if creds is None:
        return
    login, password = creds
    row = await store.get_by_username(login)
    if row is None:
        await store.create_user(login, hash_password(password), role="admin")
        logging.info("Admin created by system at %s", datetime.now(timezone.utc))
        return
    if verify_password(password, row[2]):
        return
    await store.update_password(login, hash_password(password))


async def main() -> None:
    cfg = Config.load(DEFAULT_CONFIG)
    engine = make_engine(cfg.database_url)
    try:
        store = PostgresAccounts(make_session_factory(engine))
        await ensure_admin(store)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    if get_admin_credentials() is None:
        sys.exit(0)
    asyncio.run(main())
