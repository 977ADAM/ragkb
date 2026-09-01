"""Alembic: схема истории. Запросы к базе в приложении остаются на sqlite3."""
from __future__ import annotations

import os
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import create_engine, text

_BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from ragkb.core.config import DEFAULT_CONFIG, Config

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

USER_VERSION_TO_REVISION = {
    1: "0001_base",
    2: "0002_conv_updated_index",
    3: "0003_message_model",
    4: "0004_users_sessions",
}


def _db_path() -> Path | None:
    x_args = context.get_x_argument(as_dictionary=True)
    if x_args.get("db_path"):
        return Path(x_args["db_path"]).resolve()
    env_path = os.environ.get("RAGKB_HISTORY_PATH")
    if env_path:
        return Path(env_path).resolve()
    cfg = Config.load(DEFAULT_CONFIG)
    return Path(cfg.history.path).resolve()


def run_migrations_offline() -> None:
    raise RuntimeError("Офлайн-миграции не используются: нужен файл SQLite")


def run_migrations_online() -> None:
    path = _db_path()
    if path is None:
        # history.enabled: false — не трогаем файловую систему.
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        os.close(os.open(str(path), os.O_CREAT | os.O_EXCL, 0o600))
    url = "sqlite:///" + str(path)
    engine = create_engine(url)
    with engine.connect() as conn:
        user_version = conn.execute(text("PRAGMA user_version")).scalar() or 0
        has_table = conn.execute(
            text(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='alembic_version'"
            )
        ).scalar()
        rows = []
        if has_table:
            rows = list(conn.execute(text("SELECT version_num FROM alembic_version")))
        if not rows and user_version > 0:
            revision = USER_VERSION_TO_REVISION.get(int(user_version))
            if revision is None:
                raise RuntimeError(
                    f"Неизвестная PRAGMA user_version={user_version} в {path}"
                )
            conn.execute(
                text(
                    "CREATE TABLE IF NOT EXISTS alembic_version "
                    "(version_num VARCHAR(32) NOT NULL)"
                )
            )
            conn.execute(text("DELETE FROM alembic_version"))
            conn.execute(
                text("INSERT INTO alembic_version (version_num) VALUES (:r)"),
                {"r": revision},
            )
        conn.commit()
        context.configure(connection=conn, target_metadata=None)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
