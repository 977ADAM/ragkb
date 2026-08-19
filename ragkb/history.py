"""Хранилище диалогов.

SQLite из стандартной библиотеки: новых зависимостей ноль, один файл для
резервного копирования, запас по нагрузке многократный. База Keycloak
не переиспользуется — это связало бы наши данные с чужой схемой, которая
живёт по своим правилам обновления.

Соединение открывается на запрос: FastAPI выполняет синхронные обработчики
в пуле потоков, а соединение SQLite между потоками переносить нельзя.
"""
from __future__ import annotations

import json
import re
import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

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


# Заголовок диалога — обрезанный первый вопрос. Без обращения к модели:
# так он детерминирован и не зависит от доступности LLM.
TITLE_LIMIT = 60


def make_title(question: str) -> str:
    title = re.sub(r"\s+", " ", question).strip()
    return title[:TITLE_LIMIT] if len(title) > TITLE_LIMIT else title


@dataclass(frozen=True)
class Conversation:
    id: str
    title: str
    created_at: str
    updated_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


@dataclass(frozen=True)
class Message:
    role: str
    text: str
    created_at: str
    sources: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "text": self.text,
            "created_at": self.created_at,
            "sources": self.sources,
        }


class HistoryStore:
    """Диалоги, привязанные к владельцу.

    Владелец — непрозрачная строка, та же, что даёт шов идентификации.
    Хранилище про способ аутентификации ничего не знает.

    Во всех запросах стоит условие по владельцу: фильтрация живёт в SQL,
    а не в интерфейсе, поэтому чужой идентификатор, подставленный руками,
    ничего не возвращает.
    """

    def __init__(self, path: str | Path, retention_days: int = 90):
        self.path = Path(path)
        self.retention_days = retention_days
        with connect(self.path) as conn:
            init_schema(conn)

    # ------------------------------------------------------------- запись

    def create_conversation(self, user: str, title: str) -> str:
        conversation_id = str(uuid.uuid4())
        now = utcnow().isoformat()
        with connect(self.path) as conn:
            conn.execute(
                "INSERT INTO conversations (id, user, title, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?)",
                (conversation_id, user, title, now, now),
            )
        return conversation_id

    def append(
        self,
        conversation_id: str,
        user: str,
        role: str,
        text: str,
        sources: list[dict[str, Any]] | None = None,
    ) -> bool:
        """Дописывает сообщение. False — диалога нет или он чужой."""
        now = utcnow().isoformat()
        with connect(self.path) as conn:
            owner = conn.execute(
                "SELECT 1 FROM conversations WHERE id = ? AND user = ?",
                (conversation_id, user),
            ).fetchone()
            if owner is None:
                return False
            conn.execute(
                "INSERT INTO messages (conversation_id, role, text, sources_json,"
                " created_at) VALUES (?, ?, ?, ?, ?)",
                (conversation_id, role, text,
                 json.dumps(sources or [], ensure_ascii=False), now),
            )
            conn.execute(
                "UPDATE conversations SET updated_at = ? WHERE id = ?",
                (now, conversation_id),
            )
        return True

    # ------------------------------------------------------------- чтение

    def owns(self, conversation_id: str, user: str) -> bool:
        with connect(self.path) as conn:
            row = conn.execute(
                "SELECT 1 FROM conversations WHERE id = ? AND user = ?",
                (conversation_id, user),
            ).fetchone()
        return row is not None

    def list_conversations(self, user: str, limit: int = 50) -> list[Conversation]:
        with connect(self.path) as conn:
            rows = conn.execute(
                "SELECT id, title, created_at, updated_at FROM conversations"
                " WHERE user = ? ORDER BY updated_at DESC LIMIT ?",
                (user, limit),
            ).fetchall()
        return [
            Conversation(r["id"], r["title"], r["created_at"], r["updated_at"])
            for r in rows
        ]

    def get_messages(self, conversation_id: str, user: str) -> list[Message] | None:
        """Сообщения диалога. None — диалога нет или он чужой."""
        with connect(self.path) as conn:
            owner = conn.execute(
                "SELECT 1 FROM conversations WHERE id = ? AND user = ?",
                (conversation_id, user),
            ).fetchone()
            if owner is None:
                return None
            rows = conn.execute(
                "SELECT role, text, sources_json, created_at FROM messages"
                " WHERE conversation_id = ? ORDER BY id",
                (conversation_id,),
            ).fetchall()
        return [
            Message(
                role=r["role"],
                text=r["text"],
                created_at=r["created_at"],
                sources=json.loads(r["sources_json"]),
            )
            for r in rows
        ]

    def recent_turns(
        self, conversation_id: str, user: str, window: int
    ) -> list[tuple[str, str]]:
        """Последние законченные пары «вопрос — ответ» для _condense.

        Незавершённая пара (вопрос без ответа) отбрасывается: подавать её
        в переформулировку нечем.
        """
        messages = self.get_messages(conversation_id, user)
        if not messages:
            return []
        turns: list[tuple[str, str]] = []
        pending: str | None = None
        for message in messages:
            if message.role == "user":
                pending = message.text
            elif pending is not None:
                turns.append((pending, message.text))
                pending = None
        return turns[-window:] if window > 0 else []

    # ------------------------------------------------------------ удаление

    def delete_conversation(self, conversation_id: str, user: str) -> bool:
        with connect(self.path) as conn:
            cur = conn.execute(
                "DELETE FROM conversations WHERE id = ? AND user = ?",
                (conversation_id, user),
            )
        return cur.rowcount > 0

    # -------------------------------------------------------------- уборка

    # Не чаще раза в сутки: уборка идёт внутри пользовательского запроса.
    CLEANUP_INTERVAL_DAYS = 1

    def cleanup(self, now: datetime | None = None, batch: int = 500) -> int:
        """Удаляет просроченные диалоги. Возвращает число удалённых.

        Планировщика нет: при расчётной нагрузке в сотню запросов в день
        проверка в начале запроса срабатывает регулярно, а кода на порядок
        меньше, чем у фоновой задачи с её жизненным циклом и падениями.

        Отметка обновляется атомарно. Наивная последовательность «прочитал,
        сравнил, записал» в многопоточном обработчике дала бы гонку: два
        запроса после суток простоя оба увидели бы просроченную отметку
        и оба запустили бы удаление.

        Удаление идёт порциями: после долгого простоя просроченного может
        накопиться много, а уборка выполняется внутри запроса пользователя.
        Остаток уберётся на следующем срабатывании.
        """
        now = now or utcnow()
        due_before = (now - timedelta(days=self.CLEANUP_INTERVAL_DAYS)).isoformat()
        expired_before = (now - timedelta(days=self.retention_days)).isoformat()
        with connect(self.path) as conn:
            claimed = conn.execute(
                "UPDATE cleanup_state SET last_run = ?"
                " WHERE id = 1 AND last_run < ?",
                (now.isoformat(), due_before),
            )
            if claimed.rowcount == 0:
                return 0
            # DELETE ... LIMIT собран не во всех сборках SQLite,
            # поэтому ограничиваем через подзапрос.
            removed = conn.execute(
                "DELETE FROM conversations WHERE id IN ("
                " SELECT id FROM conversations WHERE updated_at < ? LIMIT ?)",
                (expired_before, batch),
            )
        return removed.rowcount
