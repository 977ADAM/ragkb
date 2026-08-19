"""Хранилище диалогов.

SQLite из стандартной библиотеки: новых зависимостей ноль, один файл для
резервного копирования, запас по нагрузке многократный. База Keycloak
не переиспользуется — это связало бы наши данные с чужой схемой, которая
живёт по своим правилам обновления.

Соединение открывается на запрос: FastAPI выполняет синхронные обработчики
в пуле потоков, а соединение SQLite между потоками переносить нельзя.
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

# Версия схемы, которую понимает этот код. Хранится в PRAGMA user_version —
# отдельная таблица миграций не нужна, хватает номера и лестницы обновлений.
SCHEMA_VERSION = 1

_SCHEMA_V1 = """
CREATE TABLE IF NOT EXISTS conversations (
    id         TEXT PRIMARY KEY,
    user       TEXT NOT NULL,
    title      TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_conv_user ON conversations(user, updated_at DESC);

CREATE TABLE IF NOT EXISTS messages (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role            TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    text            TEXT NOT NULL,
    sources_json    TEXT NOT NULL DEFAULT '[]',
    created_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_msg_conv ON messages(conversation_id, id);

-- Одна строка с отметкой последней уборки. CHECK (id = 1) не даёт завести вторую.
CREATE TABLE IF NOT EXISTS cleanup_state (
    id       INTEGER PRIMARY KEY CHECK (id = 1),
    last_run TEXT NOT NULL
);
INSERT OR IGNORE INTO cleanup_state (id, last_run)
VALUES (1, '1970-01-01T00:00:00+00:00');
"""


def utcnow() -> datetime:
    """Текущее время в UTC. Отдельной функцией — чтобы тесты могли задать своё."""
    return datetime.now(timezone.utc)


@contextmanager
def connect(path: str | Path) -> Iterator[sqlite3.Connection]:
    """Соединение на одну операцию, с обязательными настройками SQLite."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=5)
    try:
        # Внешние ключи в SQLite выключены по умолчанию, а внутри транзакции
        # переключение не действует — только здесь, сразу после connect.
        conn.execute("PRAGMA foreign_keys = ON")
        # Без WAL запись блокирует чтение.
        conn.execute("PRAGMA journal_mode = WAL")
        conn.row_factory = sqlite3.Row
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_schema(conn: sqlite3.Connection) -> None:
    """Создаёт схему и проставляет версию. Безопасно вызывать повторно."""
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    if version > SCHEMA_VERSION:
        raise RuntimeError(
            f"База диалогов имеет версию схемы {version}, а этот код знает "
            f"только {SCHEMA_VERSION}. Похоже, релиз откатили, а база осталась "
            f"новой. Работать по непонятной схеме нельзя: верните прежнюю "
            f"версию сервиса либо уберите файл базы."
        )
    if version < 1:
        conn.executescript(_SCHEMA_V1)
        # PRAGMA не принимает параметры подстановки; SCHEMA_VERSION — константа.
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
