from __future__ import annotations

import os
from pathlib import Path

from alembic import command
from alembic.config import Config as AlembicConfig

BACKEND_ROOT = Path(__file__).resolve().parents[1]


def migrate(db_path: Path) -> None:
    os.environ["RAGKB_HISTORY_PATH"] = str(Path(db_path).resolve())
    cfg = AlembicConfig(str(BACKEND_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_ROOT / "migrations"))
    command.upgrade(cfg, "head")
