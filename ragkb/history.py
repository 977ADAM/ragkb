"""Хранилище диалогов.

SQLite из стандартной библиотеки: новых зависимостей ноль, один файл для
резервного копирования, запас по нагрузке многократный. База Keycloak
не переиспользуется — это связало бы наши данные с чужой схемой, которая
живёт по своим правилам обновления.

Соединение открывается на запрос: FastAPI выполняет синхронные обработчики
в пуле потоков, а соединение SQLite между потоками переносить нельзя.
"""
from __future__ import annotations

import contextlib
import json
import os
import re
import sqlite3
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

# Версия схемы, которую понимает этот код. Хранится в PRAGMA user_version —
# отдельная таблица миграций не нужна, хватает номера и лестницы обновлений.
SCHEMA_VERSION = 2

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

# v2: индекс по updated_at — уборка (задача 3) фильтрует по этому полю
# без фильтра по владельцу, поэтому составной idx_conv_user(user, updated_at)
# ей не помогает и запрос уходит в полное сканирование таблицы.
_SCHEMA_V2 = """
CREATE INDEX IF NOT EXISTS idx_conv_updated ON conversations(updated_at);
"""


def utcnow() -> datetime:
    """Текущее время в UTC. Отдельной функцией — чтобы тесты могли задать своё."""
    return datetime.now(timezone.utc)


@contextmanager
def connect(path: str | Path) -> Iterator[sqlite3.Connection]:
    """Соединение на одну операцию, с обязательными настройками SQLite."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Файл создаём заранее и с правами 0o600 ДО того, как sqlite3.connect
    # его откроет: база хранит журнал вопросов сотрудников, читать его
    # любому пользователю хоста (права по умолчанию 0o644) нельзя.
    # os.chmod на несуществующем файле упал бы, поэтому создаём его сами
    # через os.open с нужным режимом (учитывает umask, как и обычное
    # создание файла) — и только если файла ещё нет: на каждое соединение
    # выставлять права незачем.
    if not path.exists():
        # Гонка безвредна: соединение другого потока уже создало файл.
        with contextlib.suppress(FileExistsError):
            os.close(os.open(str(path), os.O_CREAT | os.O_EXCL, 0o600))
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
    """Создаёт схему и проставляет версию. Безопасно вызывать повторно.

    Лестница миграций: каждая ступень поднимает user_version до своего
    номера, а не сразу до SCHEMA_VERSION. Так база, застрявшая на
    промежуточной версии, докатывается по ступеням, и версию всегда
    проставляет последняя фактически применённая ступень.
    """
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
        # PRAGMA не принимает параметры подстановки; используем литерал ступени.
        conn.execute("PRAGMA user_version = 1")
    if version < 2:
        conn.executescript(_SCHEMA_V2)
        conn.execute("PRAGMA user_version = 2")


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

    def list_conversations(
        self, user: str, limit: int = 50, offset: int = 0
    ) -> list[Conversation]:
        with connect(self.path) as conn:
            rows = conn.execute(
                "SELECT id, title, created_at, updated_at FROM conversations"
                " WHERE user = ? ORDER BY updated_at DESC LIMIT ? OFFSET ?",
                (user, limit, offset),
            ).fetchall()
        return [
            Conversation(r["id"], r["title"], r["created_at"], r["updated_at"])
            for r in rows
        ]

    def count_conversations(self, user: str) -> int:
        """Общее число диалогов пользователя — для пагинации на клиенте."""
        with connect(self.path) as conn:
            row = conn.execute(
                "SELECT count(*) FROM conversations WHERE user = ?", (user,)
            ).fetchone()
        return row[0]

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

        Поднимает только хвост диалога, а не всю историю: пар нужно
        `window`, значит с запасом на незавершённую пару в конце хватает
        `window * 2 + 1` последних сообщений — `ORDER BY id DESC LIMIT ?`
        с разворотом обратно в хронологический порядок. На диалоге в
        сотни сообщений это отличие на каждый /ask по длинному диалогу.
        `sources_json` для склейки пар не нужен вовсе, поэтому не читаем
        и не парсим его тут (в отличие от get_messages).
        """
        if window <= 0:
            return []
        with connect(self.path) as conn:
            owner = conn.execute(
                "SELECT 1 FROM conversations WHERE id = ? AND user = ?",
                (conversation_id, user),
            ).fetchone()
            if owner is None:
                return []
            rows = conn.execute(
                "SELECT role, text FROM messages WHERE conversation_id = ?"
                " ORDER BY id DESC LIMIT ?",
                (conversation_id, window * 2 + 1),
            ).fetchall()
        turns: list[tuple[str, str]] = []
        pending: str | None = None
        for row in reversed(rows):
            if row["role"] == "user":
                pending = row["text"]
            elif pending is not None:
                turns.append((pending, row["text"]))
                pending = None
        return turns[-window:]

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
        Если за одну порцию удалено ровно `batch` записей, значит просроченное
        кончилось не всё — отметка немедленно возвращается в прошлое, чтобы
        следующий же запрос продолжил уборку, не дожидаясь суток. Остаток,
        который не уместился в порцию, убирается на следующем запросе, а не
        через сутки.
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
            if removed.rowcount == batch:
                # Порция выбрана целиком — просроченных, скорее всего, ещё
                # много. Суточный гейт не должен ждать: откатываем отметку,
                # чтобы следующий запрос сразу же продолжил уборку.
                conn.execute(
                    "UPDATE cleanup_state SET last_run = ? WHERE id = 1",
                    ("1970-01-01T00:00:00+00:00",),
                )
        return removed.rowcount
