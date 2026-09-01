"""Логи процесса: консоль и опционально файлы с ротацией."""
from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

DEFAULT_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
DEFAULT_DATE = "%Y-%m-%d %H:%M:%S"
_MAX_BYTES = 10_485_760
_BACKUPS = 5


def setup_logging(*, level: str = "INFO", log_dir: Path | str | None = None) -> None:
    """Перенастраивает корневой логгер. Повторный вызов безопасен (тесты, reload)."""
    numeric = getattr(logging, str(level).upper(), logging.INFO)
    logging.disable(logging.NOTSET)
    root = logging.getLogger()
    root.disabled = False
    for handler in root.handlers[:]:
        handler.close()
        root.removeHandler(handler)
    root.setLevel(numeric)
    app_log = logging.getLogger("ragkb")
    app_log.disabled = False
    app_log.handlers.clear()
    app_log.setLevel(numeric)
    app_log.propagate = True
    formatter = logging.Formatter(DEFAULT_FORMAT, DEFAULT_DATE)

    console = logging.StreamHandler(sys.stdout)
    console.setLevel(numeric)
    console.setFormatter(formatter)
    root.addHandler(console)

    if log_dir:
        directory = Path(log_dir)
        directory.mkdir(parents=True, exist_ok=True)
        app = RotatingFileHandler(
            directory / "app.log",
            maxBytes=_MAX_BYTES,
            backupCount=_BACKUPS,
            encoding="utf-8",
        )
        app.setLevel(numeric)
        app.setFormatter(formatter)
        root.addHandler(app)
        errors = RotatingFileHandler(
            directory / "errors.log",
            maxBytes=_MAX_BYTES,
            backupCount=_BACKUPS,
            encoding="utf-8",
        )
        errors.setLevel(logging.ERROR)
        errors.setFormatter(formatter)
        root.addHandler(errors)

    for name in ("httpx", "httpcore", "urllib3", "chromadb", "huggingface_hub"):
        logging.getLogger(name).setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
