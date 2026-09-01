# Postgres SQLAlchemy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** История диалогов и локальные аккаунты живут в Postgres через SQLAlchemy 2 async; схема — Alembic; SQLite для этого больше нет.

**Architecture:** Модели в слайсах `chat_conversations` и `auth`. `platform/db.py` — `AsyncEngine`, `async_sessionmaker`, константа head. Адаптеры принимают фабрику сессий. Alembic синхронно через `+psycopg`. Ручки auth, chat_conversations, bootstrap и `current_user` / `require_admin` — `async def`. Search/models/organization/index/telemetry остаются `def`.

**Tech Stack:** Python 3.10+, FastAPI, SQLAlchemy 2, asyncpg, psycopg 3, Alembic, Postgres 16, pytest-asyncio.

**Спека:** `docs/superpowers/specs/2026-09-01-postgres-sqlalchemy-design.md`

## Global Constraints

- Рантайм: `postgresql+asyncpg://…` + `AsyncSession`. Alembic: тот же URL с заменой `+asyncpg` → `+psycopg`.
- `sqlalchemy` / `alembic` запрещены в `ragkb/core/`. В `features/` и `platform/` — можно. Alembic `env.py` импортирует модели слайсов (это не пакет `ragkb.core`).
- Слайсовый `service.py` не импортирует чужие `ragkb.features.*` (кроме bootstrap).
- `router.py` слайса не импортирует `ragkb.core` и `*.ports`.
- Колонка владельца диалога в БД — `owner`, не `user`.
- `RAGKB_DATABASE_URL` обязателен, если `history.enabled` или `auth.mode == "session"`. Иначе (`disabled` + история выкл.) URL не нужен.
- Старый SQLite не переносим. Коммит после каждой задачи. Не пушить, пока не попросят.
- Исторические планы в `docs/superpowers/plans/` не переписывать.
- Язык комментариев и пользовательских `detail` — русский.
- HTTP входа и чата не менять (пути, тела, кука `ragkb_session`).
- Тесты, которым нужна БД: `RAGKB_TEST_DATABASE_URL` иначе `RAGKB_DATABASE_URL`. Нет URL — падать с текстом про postgres, не skip.
- `pytest-asyncio` в extra `dev`; `asyncio_mode = auto` в `[tool.pytest.ini_options]`.

## File map

**Создать**

- `backend/ragkb/platform/db.py` — URL helpers, engine, sessionmaker, `EXPECTED_REVISION`, `needs_database`
- `backend/ragkb/features/chat_conversations/models.py`
- `backend/ragkb/features/auth/models.py`
- `backend/ragkb/features/chat_conversations/postgres.py` — `PostgresHistory`
- `backend/ragkb/features/auth/postgres.py` — `PostgresAccounts`
- `backend/migrations/versions/0001_postgres_history_auth.py`

**Удалить**

- `backend/migrations/versions/0001_base.py`, `0002_conv_updated_index.py`, `0003_message_model.py`, `0004_users_sessions.py`
- `backend/ragkb/features/chat_conversations/sqlite.py`
- `backend/ragkb/features/auth/sqlite.py`

**Менять**

- `backend/pyproject.toml` / `uv.lock`
- `backend/migrations/env.py`
- `backend/ragkb/core/config.py` — `database_url`, убрать `history.path`
- `backend/ragkb/features/chat_conversations/ports.py` — `async def`
- `backend/ragkb/features/chat_conversations/ephemeral.py`
- `backend/ragkb/features/chat_conversations/service.py`, `router.py`
- `backend/ragkb/features/auth/ports.py`, `service.py`, `router.py`
- `backend/ragkb/features/bootstrap/service.py`, `router.py`
- `backend/ragkb/platform/auth.py`, `container.py`, `app.py`
- `backend/tests/helpers.py`, `conftest.py`, `test_architecture.py`, `test_history.py`, `test_session_auth.py`, `test_guard.py`, `test_logging.py`
- `docker-compose.yml`, `Makefile`, `deploy.sh`, `.github/workflows/deploy.yml`, `.env.example`, `README.md`, `AGENTS.md`, `.cursor/rules/repo-layout.mdc`

---

### Task 1: Зависимости, URL, Alembic с нуля

**Files:**
- Modify: `backend/pyproject.toml`
- Modify: `backend/migrations/env.py`
- Create: `backend/migrations/versions/0001_postgres_history_auth.py`
- Delete: четыре sqlite-ревизии
- Modify: `backend/ragkb/core/config.py`
- Modify: `backend/tests/helpers.py`
- Modify: `backend/tests/test_architecture.py`
- Modify: `backend/tests/test_session_auth.py` (только тест схемы)
- Run: `cd backend && uv lock && uv sync --extra migrations --extra dev`

**Interfaces:**
- Consumes: Postgres, доступный по URL
- Produces: `Config.database_url: str = ""`; `RAGKB_DATABASE_URL`; `alembic_sync_url(url: str) -> str`; ревизия id `0001_postgres_history_auth`; `helpers.database_url() -> str`; `helpers.migrate() -> None` (без пути SQLite)

- [ ] **Step 1: Write the failing test**

В `backend/tests/helpers.py` заменить `migrate`:

```python
from __future__ import annotations

import os
from pathlib import Path

from alembic import command
from alembic.config import Config as AlembicConfig

BACKEND_ROOT = Path(__file__).resolve().parents[1]


def database_url() -> str:
    url = os.environ.get("RAGKB_TEST_DATABASE_URL") or os.environ.get(
        "RAGKB_DATABASE_URL", ""
    )
    if not url:
        raise RuntimeError(
            "Для тестов нужен Postgres: задайте RAGKB_TEST_DATABASE_URL "
            "или RAGKB_DATABASE_URL (postgresql+asyncpg://…)."
        )
    return url


def alembic_sync_url(url: str) -> str:
    return url.replace("+asyncpg", "+psycopg", 1)


def migrate() -> None:
    os.environ["RAGKB_DATABASE_URL"] = database_url()
    cfg = AlembicConfig(str(BACKEND_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_ROOT / "migrations"))
    command.upgrade(cfg, "head")
```

В `test_session_auth.py` заменить `test_migrate_creates_users_and_sessions` на:

```python
from sqlalchemy import create_engine, text

from helpers import alembic_sync_url, database_url, migrate


def test_migrate_creates_postgres_tables() -> None:
    migrate()
    engine = create_engine(alembic_sync_url(database_url()))
    with engine.connect() as conn:
        names = {
            r[0]
            for r in conn.execute(
                text(
                    "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
                )
            )
        }
        assert "users" in names
        assert "sessions" in names
        assert "conversations" in names
        assert "messages" in names
        rev = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
        assert rev == "0001_postgres_history_auth"
        owner = conn.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'conversations' AND column_name = 'owner'"
            )
        ).scalar()
        assert owner == "owner"
```

В `test_architecture.py` `test_sqlalchemy_only_in_migrations` заменить на проверку только `PKG / "core"`:

```python
def test_sqlalchemy_not_in_core():
    forbidden = ("sqlalchemy", "alembic")
    for path in _py_files(PKG / "core"):
        for name in _imports(path):
            root = name.split(".")[0]
            assert root not in forbidden, path
    for path in _py_files(MIGRATIONS):
        for name in _imports(path):
            if name.startswith("ragkb.") and not name.startswith(
                ("ragkb.core.config", "ragkb.features.")
            ):
                pytest.fail(f"{path} импортирует {name}")
```

`test_expected_revision_matches_alembic_head`: временно сравнивать `script.get_current_head() == "0001_postgres_history_auth"` (константу в `platform/db.py` подключите в задаче 2).

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_session_auth.py::test_migrate_creates_postgres_tables tests/test_architecture.py::test_expected_revision_matches_alembic_head -q`

Expected: FAIL (нет ревизии / sqlite env.py)

- [ ] **Step 3: Write minimal implementation**

`pyproject.toml` dependencies: `"sqlalchemy[asyncio]>=2.0"`, `"asyncpg>=0.29"`. Extra `migrations`: `"alembic>=1.13"`, `"psycopg[binary]>=3.1"`. Extra `dev`: добавить `"pytest-asyncio>=0.24"`.

`HistoryConfig`: удалить поле `path`. `Config`: добавить `database_url: str = ""`. В `_apply_env` убрать `RAGKB_HISTORY_PATH`, добавить `"RAGKB_DATABASE_URL": ("database_url", self)`.

`env.py` целиком:

```python
"""Alembic: схема Postgres. Приложение схему не накатывает."""
from __future__ import annotations

import os
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import create_engine, pool

_BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from ragkb.core.config import DEFAULT_CONFIG, Config

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)


def _async_url() -> str:
    x_args = context.get_x_argument(as_dictionary=True)
    if x_args.get("url"):
        return x_args["url"]
    env = os.environ.get("RAGKB_DATABASE_URL")
    if env:
        return env
    return Config.load(DEFAULT_CONFIG).database_url


def _sync_url(url: str) -> str:
    if not url:
        raise RuntimeError("Задайте RAGKB_DATABASE_URL")
    return url.replace("+asyncpg", "+psycopg", 1)


def run_migrations_offline() -> None:
    raise RuntimeError("Офлайн-миграции не используются")


def run_migrations_online() -> None:
    url = _sync_url(_async_url())
    engine = create_engine(url, poolclass=pool.NullPool)
    with engine.connect() as conn:
        context.configure(connection=conn, target_metadata=None)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
```

Ревизия `0001_postgres_history_auth.py` (`down_revision = None`):

```python
from alembic import op

revision = "0001_postgres_history_auth"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE conversations (
            id UUID PRIMARY KEY,
            owner TEXT NOT NULL,
            title TEXT NOT NULL DEFAULT '',
            created_at TIMESTAMPTZ NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL
        )
        """
    )
    op.execute(
        "CREATE INDEX idx_conv_owner ON conversations (owner, updated_at DESC)"
    )
    op.execute("CREATE INDEX idx_conv_updated ON conversations (updated_at)")
    op.execute(
        """
        CREATE TABLE messages (
            id BIGSERIAL PRIMARY KEY,
            conversation_id UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
            role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
            text TEXT NOT NULL,
            sources JSONB NOT NULL DEFAULT '[]'::jsonb,
            model TEXT NOT NULL DEFAULT '',
            created_at TIMESTAMPTZ NOT NULL
        )
        """
    )
    op.execute("CREATE INDEX idx_msg_conv ON messages (conversation_id, id)")
    op.execute(
        """
        CREATE TABLE cleanup_state (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            last_run TIMESTAMPTZ NOT NULL
        )
        """
    )
    op.execute(
        "INSERT INTO cleanup_state (id, last_run) "
        "VALUES (1, TIMESTAMPTZ '1970-01-01 00:00:00+00')"
    )
    op.execute(
        """
        CREATE TABLE users (
            id UUID PRIMARY KEY,
            username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL
        )
        """
    )
    op.execute(
        """
        CREATE TABLE sessions (
            token_hash TEXT PRIMARY KEY,
            user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            expires_at TIMESTAMPTZ NOT NULL
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS sessions")
    op.execute("DROP TABLE IF EXISTS users")
    op.execute("DROP TABLE IF EXISTS messages")
    op.execute("DROP TABLE IF EXISTS conversations")
    op.execute("DROP TABLE IF EXISTS cleanup_state")
```

Удалить sqlite-ревизии. `uv lock && uv sync --extra migrations --extra dev`.

В `test_architecture.py` head сравнивать со строкой `"0001_postgres_history_auth"`.

- [ ] **Step 4: Run the tests and make sure they pass**

Run: `cd backend && uv run pytest tests/test_session_auth.py::test_migrate_creates_postgres_tables tests/test_architecture.py -q`

Expected: PASS (нужен Postgres в URL)

- [ ] **Step 5: Commit**

```bash
git add backend/pyproject.toml backend/uv.lock backend/migrations \
  backend/ragkb/core/config.py backend/tests/helpers.py \
  backend/tests/test_architecture.py backend/tests/test_session_auth.py
git commit -m "$(cat <<'EOF'
Перевести Alembic на Postgres и URL приложения.

Цепочка SQLite снята; схема с нуля, включая users и sessions.
EOF
)"
```

---

### Task 2: Модели и фабрика сессий

**Files:**
- Create: `backend/ragkb/features/chat_conversations/models.py`
- Create: `backend/ragkb/features/auth/models.py`
- Create: `backend/ragkb/platform/db.py`
- Modify: `backend/tests/test_architecture.py` (head из `EXPECTED_REVISION`)
- Modify: `backend/migrations/env.py` — `target_metadata` из моделей (опционально, SQL уже в ревизии; импорт моделей нужен, чтобы они не расходились)

**Interfaces:**
- Produces:
  - `EXPECTED_REVISION = "0001_postgres_history_auth"`
  - `def needs_database(cfg: Config) -> bool`
  - `def alembic_sync_url(url: str) -> str`
  - `def make_engine(url: str) -> AsyncEngine`
  - `def make_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]`
  - `async def assert_revision(session: AsyncSession) -> None`
  - модели: `ConversationRow`, `MessageRow`, `CleanupStateRow`, `UserRow`, `SessionRow`

- [ ] **Step 1: Write the failing tests**

Добавить в `test_session_auth.py`:

```python
import pytest
from sqlalchemy import select

from ragkb.features.auth.models import UserRow
from ragkb.platform.db import EXPECTED_REVISION, make_engine, make_session_factory


@pytest.mark.asyncio
async def test_models_roundtrip_user() -> None:
    migrate()
    engine = make_engine(database_url())
    factory = make_session_factory(engine)
    async with factory() as session:
        session.add(
            UserRow(
                id="11111111-1111-4111-8111-111111111111",
                username="ada",
                password_hash="x",
            )
        )
        await session.commit()
        row = (
            await session.execute(select(UserRow).where(UserRow.username == "ada"))
        ).scalar_one()
        assert row.username == "ada"
    await engine.dispose()
```

`test_expected_revision_matches_alembic_head` импортирует `EXPECTED_REVISION` из `ragkb.platform.db`.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_session_auth.py::test_models_roundtrip_user -q`

Expected: FAIL import

- [ ] **Step 3: Write minimal implementation**

Общий `DeclarativeBase` в `platform/db.py` (`class Base(DeclarativeBase)`), слайсы импортируют `Base` оттуда (не наоборот: модели слайса не импортируют контейнер).

`models.py` диалогов: `__tablename__`, `Mapped` типы UUID/str/datetime/JSONB (`from sqlalchemy.dialects.postgresql import JSONB, UUID`). `ConversationRow.owner`. `created_at` default `func.now()` или задавать в адаптере.

`UserRow.created_at` / `SessionRow.expires_at` — `DateTime(timezone=True)`.

`needs_database`: `return cfg.history.enabled or cfg.auth.mode == "session"`.

`assert_revision`: `SELECT version_num FROM alembic_version`; иначе `RuntimeError` с текстом как у sqlite (выполните alembic upgrade head).

`make_engine`: `create_async_engine(url, pool_pre_ping=True)`.

- [ ] **Step 4: Run the tests**

Run: `cd backend && uv run pytest tests/test_session_auth.py::test_models_roundtrip_user tests/test_architecture.py::test_expected_revision_matches_alembic_head -q`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/ragkb/platform/db.py \
  backend/ragkb/features/chat_conversations/models.py \
  backend/ragkb/features/auth/models.py \
  backend/tests/test_architecture.py backend/tests/test_session_auth.py \
  backend/migrations/env.py
git commit -m "$(cat <<'EOF'
Добавить модели SQLAlchemy и фабрику AsyncSession.

Head Alembic совпадает с EXPECTED_REVISION в platform.
EOF
)"
```

---

### Task 3: Async-порты и PostgresHistory

**Files:**
- Modify: `backend/ragkb/features/chat_conversations/ports.py`
- Modify: `backend/ragkb/features/chat_conversations/ephemeral.py`
- Create: `backend/ragkb/features/chat_conversations/postgres.py`
- Delete: `backend/ragkb/features/chat_conversations/sqlite.py`
- Modify: `backend/tests/test_history.py`

**Interfaces:**
- Produces: все методы `ConversationRepository` / `AnswerHistory` / `EphemeralHistory` — `async def`. `PostgresHistory(session_factory, retention_days: int = 90)` с `await assert_revision` в `__init__` нельзя (init sync) — вызов `assert_revision` в первой операции или отдельный `async def ready()`. Предпочтение: `async def ready(self) -> None` вызывается из lifespan контейнера; тесты зовут `await store.ready()` после конструктора.
- `created_at` / `updated_at` в `Conversation` / `Message` по-прежнему `str` (`.isoformat()`).
- `cleanup` сравнивает timestamptz, не строки.

Сигнатуры портов (все async):

```python
async def create(self, user: str) -> str: ...
async def owns(self, conversation_id: str, user: str) -> bool: ...
async def list_conversations(self, user: str, limit: int = 50, offset: int = 0) -> list[Conversation]: ...
async def count_conversations(self, user: str) -> int: ...
async def get_messages(self, conversation_id: str, user: str) -> list[Message] | None: ...
async def append(...) -> bool: ...
async def set_title_if_empty(...) -> bool: ...
async def rename(...) -> bool: ...
async def delete(...) -> bool: ...
async def cleanup(self, now=None, batch: int = 500) -> int: ...
async def recent_turns(...) -> list[tuple[str, str]]: ...
```

- [ ] **Step 1: Write the failing tests**

В `test_history.py` заменить sqlite-тесты:

```python
import pytest
from ragkb.features.chat_conversations.postgres import PostgresHistory
from ragkb.platform.db import make_engine, make_session_factory
from helpers import database_url, migrate


@pytest.mark.asyncio
async def test_postgres_crud() -> None:
    migrate()
    engine = make_engine(database_url())
    store = PostgresHistory(make_session_factory(engine))
    await store.ready()
    cid = await store.create("ada")
    assert await store.owns(cid, "ada")
    assert not await store.owns(cid, "bob")
    assert await store.append(cid, "ada", "user", "вопрос")
    assert await store.set_title_if_empty(cid, "ada", "вопрос")
    assert await store.get_messages(cid, "bob") is None
    msgs = await store.get_messages(cid, "ada")
    assert msgs and msgs[0].text == "вопрос"
    await engine.dispose()
```

`test_ephemeral_create_is_uuid` — `await store.create`. `test_alembic_fresh_db` — через `pg_tables` / `alembic_version` как в задаче 1. Удалить тесты `connect` / `PRAGMA` / `user_version`.

- [ ] **Step 2: Run to verify fail**

Run: `cd backend && uv run pytest tests/test_history.py::test_postgres_crud -q`

Expected: FAIL

- [ ] **Step 3: Implement PostgresHistory**

Логика как `SqliteHistory`, фильтр `ConversationRow.owner == user`. JSONB для `sources`. UUID: `uuid.uuid4()` в `id`.

`EphemeralHistory`: те же методы с `async def`, тела без изменений.

- [ ] **Step 4: Run tests**

Run: `cd backend && uv run pytest tests/test_history.py -q`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/ragkb/features/chat_conversations backend/tests/test_history.py
git commit -m "$(cat <<'EOF'
Заменить sqlite-историю на async PostgresHistory.

Порты диалогов — async def, колонка владельца owner.
EOF
)"
```

---

### Task 4: PostgresAccounts и async AuthService

**Files:**
- Modify: `backend/ragkb/features/auth/ports.py`
- Create: `backend/ragkb/features/auth/postgres.py`
- Delete: `backend/ragkb/features/auth/sqlite.py`
- Modify: `backend/ragkb/features/auth/service.py`
- Modify: `backend/ragkb/features/auth/router.py` — импорт `COOKIE_NAME` из `postgres.py` (или перенести константы в `passwords.py`: `COOKIE_NAME`, `SESSION_DAYS`, `utcnow`)
- Modify: `backend/tests/test_session_auth.py`

**Interfaces:**
- `AccountStore` — все методы `async def`.
- `AuthService` методы `async def`; `IntegrityError` из `sqlalchemy.exc`, не `sqlite3`.
- `expires_at` в БД — timestamptz; сервис по-прежнему передаёт isoformat, адаптер парсит `datetime.fromisoformat`.
- `PostgresAccounts.ready()` как у истории.

Перенести `COOKIE_NAME`, `SESSION_DAYS`, `utcnow` в `backend/ragkb/features/auth/passwords.py` (уже есть в пакете), чтобы не держать sqlite-файл ради констант.

- [ ] **Step 1: Failing tests**

Заменить `test_accounts_user_and_session` на async + `PostgresAccounts`. Остальные HTTP-тесты сломаются до задачи 5–6 — **в этой задаче помечайте их `@pytest.mark.skip` только если падают импортом sqlite**; лучше починить импорты (`COOKIE_NAME` из `passwords`) и оставить HTTP до задачи 6 зелёными насколько возможно. Если `create_app` ещё на sqlite — HTTP тесты падают: оставить их, чинить в задаче 6. Эта задача: unit store + `test_password_roundtrip` + схема.

- [ ] **Step 2: Fail**

Run: `cd backend && uv run pytest tests/test_session_auth.py::test_accounts_user_and_session -q`

- [ ] **Step 3: Implement**

`register`/`login`/`logout`/`me` — `await`. `create_user` ловит `IntegrityError`.

- [ ] **Step 4: Pass unit tests**

Run: `cd backend && uv run pytest tests/test_session_auth.py::test_password_roundtrip tests/test_session_auth.py::test_accounts_user_and_session tests/test_session_auth.py::test_migrate_creates_postgres_tables -q`

- [ ] **Step 5: Commit**

```bash
git add backend/ragkb/features/auth backend/tests/test_session_auth.py
git commit -m "$(cat <<'EOF'
Перевести аккаунты на async PostgresAccounts.

Пароли по-прежнему Argon2; IntegrityError мапится в 409.
EOF
)"
```

---

### Task 5: async current_user, сервисы и ручки

**Files:**
- Modify: `backend/ragkb/platform/auth.py`
- Modify: `backend/ragkb/features/auth/router.py`
- Modify: `backend/ragkb/features/chat_conversations/service.py`
- Modify: `backend/ragkb/features/chat_conversations/router.py`
- Modify: `backend/ragkb/features/bootstrap/service.py`
- Modify: `backend/ragkb/features/bootstrap/router.py`

**Interfaces:**
- `async def current_user`, `optional_user`, `require_admin`
- В `session`: `await container.accounts.user_for_token_hash(digest)`
- `ChatConversationsService`: все публичные методы `async def`; `stream_message` возвращает `AsyncIterator[str]`; внутри `async for` нет у sync `engine.stream_answer` — токены по-прежнему sync iterator, `await` только на history
- `list_page` / `create` / `get` / … — `await` к репозиторию
- `BootstrapService.app_start` — `async def`, `await self.chats.list_page(...)`
- Ручки auth/chats/bootstrap — `async def`; `await svc....`
- `GET /auth/me` в session: `await svc.me(...)`; иначе `await current_user(request)`

`stream_message`: после сбора токенов `await self.history.append(...)`.

- [ ] **Step 1: Нет отдельного красного теста** — контракт уже в `test_session_auth` HTTP. Реализуйте ручки; падение `create_app` чинится в задаче 6. Здесь сделайте код компилируемым: container ещё sqlite сломает импорты — **задача 5 и 6 идут подряд в одном PR-цикле**: если импорт `SqliteHistory` уже удалён, задача 6 должна быть сразу после 5 в той же сессии агента. Исполнителю: не оставлять дерево, где `container.py` импортирует удалённый sqlite.

Минимально в этой задаче поправьте `container.py` импорты на Postgres*, даже если lifespan ещё нет: конструктор принимает `session_factory: async_sessionmaker | None`.

- [ ] **Step 2: Syntax / import check**

Run: `cd backend && uv run python -c "from ragkb.features.bootstrap.router import router"`

Expected: PASS

- [ ] **Step 3: Container stub**

Если factory `None` (нет URL): `conversations = EphemeralHistory()`, `accounts` — заглушка, которая не вызывается в disabled. Для `session` без factory — не создавать app (задача 6).

- [ ] **Step 4: pytest collect**

Run: `cd backend && uv run pytest --collect-only -q`

Expected: коллекция без ImportError

- [ ] **Step 5: Commit**

```bash
git add backend/ragkb/platform/auth.py backend/ragkb/features \
  backend/ragkb/platform/container.py
git commit -m "$(cat <<'EOF'
Сделать async ручки auth, диалогов и bootstrap.

current_user в режиме session читает таблицу sessions через ORM.
EOF
)"
```

---

### Task 6: Lifespan, гейт URL, фикстуры тестов

**Files:**
- Modify: `backend/ragkb/platform/app.py`
- Modify: `backend/ragkb/platform/container.py`
- Modify: `backend/tests/conftest.py`
- Modify: `backend/tests/test_guard.py`
- Modify: `backend/tests/test_logging.py`
- Modify: `backend/tests/test_session_auth.py` (HTTP)
- Add: `[tool.pytest.ini_options] asyncio_mode = "auto"` в `pyproject.toml` если ещё нет

**Interfaces:**
- Lifespan: если `needs_database(cfg)` — engine, factory, `PostgresHistory`/`PostgresAccounts`, `await ready()` оба; на стопе `await engine.dispose()`
- Нет URL при `needs_database` — `RuntimeError("Задайте RAGKB_DATABASE_URL")` до раздачи запросов
- `app.state.container` как сейчас
- `TestClient` остаётся (Starlette гоняет async-ручки)
- `conftest.cfg`: `migrate()`; `cfg.database_url = database_url()`; `cfg.auth.mode = "disabled"`; `history.enabled = True` для indexed; **без** `history.path`
- Между тестами TRUNCATE: фикстура autouse session-scoped migrate once; function-scoped:

```python
@pytest.fixture(autouse=True)
def _truncate(cfg):
    # только если URL задан и needs db for this cfg
    ...
```

Проще: в начале каждого теста, которому нужна БД, TRUNCATE `messages, conversations, sessions, users` RESTART IDENTITY CASCADE; `cleanup_state` вернуть epoch. Не трогать `alembic_version`.

`test_guard`: `create_app` с `disabled` + `history.enabled=False` **не** требует URL и не пишет sqlite. Утверждать, что репозиторный `data/history.sqlite3` не обязателен.

`test_create_app_logs_disabled_auth`: `history.enabled = False`, без migrate/path.

HTTP session tests: `indexed.database_url = database_url()`; `indexed.auth.mode = "session"`; `indexed.history.enabled = True`.

- [ ] **Step 1: Implement lifespan + fixtures**

```python
from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    cfg = app.state.cfg  # сохранить cfg на app.state в create_app
    c = app.state.container
    if c.engine_obj is not None:
        await c.ready()
    yield
    await c.dispose()
```

`Container.__init__`: если `needs_database` и не `cfg.database_url` — сразу `RuntimeError`. Иначе создать engine/factory/stores. Если не needs: ephemeral + `accounts=None`; `current_user` в disabled не трогает accounts.

Для `disabled` + `history.enabled` всё равно нужен URL и `PostgresHistory`; accounts можно не открывать, но проще один engine на обе модели.

- [ ] **Step 2: Run full pytest**

Run: `cd backend && uv run pytest -q`

Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add backend/ragkb/platform/app.py backend/ragkb/platform/container.py \
  backend/tests backend/pyproject.toml
git commit -m "$(cat <<'EOF'
Подключить lifespan Postgres и починить тесты на живой БД.

Без URL приложение стартует только с disabled и выключенной историей.
EOF
)"
```

---

### Task 7: Compose, Makefile, документация

**Files:**
- Modify: `docker-compose.yml`
- Modify: `Makefile`
- Modify: `deploy.sh`
- Modify: `.github/workflows/deploy.yml`
- Modify: `.env.example`
- Modify: `README.md`, `AGENTS.md`, `frontend/README.md` при упоминании sqlite-истории
- Modify: `.cursor/rules/repo-layout.mdc`

**Interfaces:**
- `postgres:16` healthcheck `pg_isready`
- `migrate.depends_on.postgres.condition: service_healthy`
- env: `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`, `RAGKB_DATABASE_URL=postgresql+asyncpg://${POSTGRES_USER}:${POSTGRES_PASSWORD}@postgres:5432/${POSTGRES_DB}`
- том `rag_pg`; том `rag_history` удалить
- `make up` / deploy: `postgres migrate rag frontend`
- `make test` help: нужна `RAGKB_TEST_DATABASE_URL`
- AGENTS: история в Postgres; sqlalchemy можно в features/platform; не в core; alembic только migrations

Пример сервиса postgres:

```yaml
  postgres:
    image: postgres:16
    environment:
      POSTGRES_USER: ${POSTGRES_USER:-ragkb}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
      POSTGRES_DB: ${POSTGRES_DB:-ragkb}
    volumes:
      - rag_pg:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER:-ragkb} -d ${POSTGRES_DB:-ragkb}"]
      interval: 2s
      timeout: 5s
      retries: 20
```

`.env.example`:

```
POSTGRES_USER=ragkb
POSTGRES_PASSWORD=
POSTGRES_DB=ragkb
RAGKB_DATABASE_URL=postgresql+asyncpg://ragkb:CHANGEME@postgres:5432/ragkb
```

- [ ] **Step 1: Правки файлов**

- [ ] **Step 2: `docker compose -f docker-compose.yml config --services`**

Expected: `postgres migrate rag frontend`

- [ ] **Step 3: `cd backend && uv run pytest -q`**

Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add docker-compose.yml Makefile deploy.sh .github/workflows/deploy.yml \
  .env.example README.md AGENTS.md frontend/README.md \
  .cursor/rules/repo-layout.mdc
git commit -m "$(cat <<'EOF'
Поднять Postgres в compose и описать URL вместо sqlite-истории.

Выкладка поднимает postgres до migrate.
EOF
)"
```

---

## Spec coverage

| Спека | Задача |
|---|---|
| compose postgres, URL, migrate ждёт healthy | 7 |
| Alembic с нуля, без PRAGMA | 1 |
| модели в слайсах, sessionmaker в platform | 2 |
| async адаптеры истории и аккаунтов | 3–4 |
| bootstrap + current_user async | 5 |
| lifespan, гейт URL, тесты Postgres, TRUNCATE | 6 |
| README/AGENTS/Makefile/deploy | 7 |
| нет переноса sqlite | явно нигде не копируем данные |
| sqlalchemy не в core | 1 architecture test |
| HTTP не меняем | 4–5 |

## Placeholder scan

Нет TBD. Имена: `PostgresHistory`, `PostgresAccounts`, `EXPECTED_REVISION`, `needs_database`, `0001_postgres_history_auth`, `ConversationRow.owner`.
