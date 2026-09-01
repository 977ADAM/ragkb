# История и аккаунты на Postgres (SQLAlchemy 2 async)

| | |
|---|---|
| Дата | 2026-09-01 |
| Версия | 1 |
| Статус | в работе |
| Автор | Cursor Grok 4.6 |

## Зачем

Диалоги и локальный вход лежат в SQLite (`sqlite3`, схема Alembic). Нужен
Postgres: классический стек SQLAlchemy 2 + Alembic, адаптеры **async**
(`AsyncSession`, asyncpg). Индекс по-прежнему Chroma, не в Postgres.

На момент спеки вход уже работает на SQLite (`users` / `sessions`, кука,
страницы `/login` `/register`). Переносить только историю нельзя: снова
два файла. Этот заход меняет **хранилище** обеих групп таблиц. Контракт
HTTP входа и UI не перепроектируем.

## Границы

**В работе:** сервис `postgres` в compose; `RAGKB_DATABASE_URL`; новая цепочка
Alembic с нуля (без `PRAGMA`); модели SQLAlchemy в слайсах `chat_conversations`
и `auth`; `AsyncEngine` / `async_sessionmaker` в `platform`; порты истории и
аккаунтов, ручки `auth` / `chat_conversations` / `bootstrap`, `current_user`
и `require_admin` — `async def`; `EphemeralHistory` тоже async; lifespan
(создать engine, `dispose` на стопе); сессия на запрос; тесты на живом
Postgres; правки README / AGENTS / `.env.example` / Makefile / deploy
(`postgres` в `compose up`); снять `history.path` / том `rag_history` /
`EXPECTED_REVISION` на SQLite; архитектурный тест: sqlalchemy нет в `core/`,
в `features/` и `platform/` — можно.

**Вне работы:** перенос данных из существующего `history.sqlite3` (новый
Postgres пустой: старые чаты и локальные учётки пропадают, регистрация
заново); вход как фича (формы, кука, правила пароля — уже есть);
Keycloak/MariaDB; смена контракта `/organization/…/chat_conversations`;
async для search/index/models/bootstrap; Chroma; разграничение документов;
SQLAlchemy в `ragkb.core`.

Ветка/план `2026-09-01-local-auth` для SQLite-адаптера не продолжаем:
хранилище меняется здесь. Спека входа по HTTP остаётся источником правды
для форм и куки.

## Конфиг и compose

Переменная `RAGKB_DATABASE_URL`: SQLAlchemy-URL с драйвером asyncpg,
например `postgresql+asyncpg://ragkb:…@postgres:5432/ragkb`.

Alembic ходит **синхронно**: в `env.py` из того же URL заменяем
`+asyncpg` на `+psycopg` (`postgresql+psycopg://…`). Отдельной env для
миграций нет.

`history.path` и `RAGKB_HISTORY_PATH` удаляем. `history.enabled` остаётся:
выкл — эфемерная память, таблицы диалогов не используются. Старт без URL
разрешён только если `auth.mode: disabled` и `history.enabled: false`
(`make backend` как сейчас). Иначе нет URL — процесс не поднимается.

Compose: `postgres` (официальный образ 16, healthcheck, том данных) →
`migrate` (`alembic upgrade head`, ждёт healthy) → `rag` → `frontend`.
Пароли БД — `.env` (`POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB`
и собранный `RAGKB_DATABASE_URL`). Приложение схему само не накатывает.

`make up`, `deploy.sh` и workflow `compose up` включают `postgres`.

## Схема

Старые ревизии SQLite (`0001`…`0004`, `user_version`) удаляем. Новая
единственная ревизия (имя вроде `0001_postgres_history_auth`) создаёт:

`conversations`: `id` UUID PK, `owner` TEXT NOT NULL (не `user` — слово
зарезервировано), `title` TEXT NOT NULL DEFAULT '', `created_at` /
`updated_at` timestamptz. Индексы: `(owner, updated_at DESC)`,
`(updated_at)`.

`messages`: `id` BIGSERIAL PK, `conversation_id` UUID FK CASCADE, `role`
TEXT с CHECK `user`/`assistant`, `text` TEXT, `sources` JSONB NOT NULL
DEFAULT `[]`, `model` TEXT NOT NULL DEFAULT '', `created_at` timestamptz.
Индекс `(conversation_id, id)`.

`cleanup_state`: одна строка (`id = 1`), `last_run` timestamptz.

`users`: как в спеке входа по смыслу — `id` UUID, `username` UNIQUE,
`password_hash`, `created_at` timestamptz.

`sessions`: `token_hash` TEXT PK, `user_id` UUID FK CASCADE, `expires_at`
timestamptz.

Проверка ревизии при старте адаптера: ровно один ряд в `alembic_version`,
равный head этой цепочки. Иначе процесс не поднимается (как сейчас).

## SQLAlchemy и слайсы

Declarative-модели рядом со слайсом (`features/chat_conversations/models.py`,
`features/auth/models.py`). Metadata собирается для Alembic импортом обеих.

`platform` отдаёт `async_sessionmaker`. Адаптеры принимают фабрику сессий,
не открывают свой engine. На HTTP-запрос: `async with Session() as session`.

Порты истории и аккаунтов — `async def`. Поэтому:

- `ChatConversationsService` (в т.ч. `list_page`) и `AuthService` — async;
- `GET /bootstrap` зовёт список диалогов — `BootstrapService.app_start` и
  ручка bootstrap тоже `async def` (без `asyncio.run` и без синхронной
  обёртки);
- `current_user` / `optional_user` / `require_admin` — `async def`: в режиме
  `session` читают `sessions` через ORM. В `disabled` / `proxy` в БД не
  ходят, сигнатура всё равно async.

Слайсы search, models, organization, index, telemetry остаются `def`.
FastAPI сначала await у async-Depends (`current_user`), потом вызывает
синхронную ручку.

HTTP-тела и пути не меняются. NDJSON на `…/messages` — async-генератор.

Зависимости пакета: `sqlalchemy[asyncio]`, `asyncpg`; extra `migrations` —
`alembic` и `psycopg` (v3). `argon2-cffi` остаётся (хеш пароля).

## Тесты

Нужен запущенный Postgres. URL: `RAGKB_TEST_DATABASE_URL`, иначе
`RAGKB_DATABASE_URL`. Нет URL — фикстура падает с текстом «поднимите
postgres» (не skip). Это отдельная БД в URL (обычно `ragkb_test`), не
боевой том. Один раз за сессию pytest: `upgrade head`. Между тестами —
TRUNCATE всех таблиц приложения (не `alembic_version`). `pytest-asyncio`
в extra `dev`. Тесты истории и `test_session_auth` — async-клиент и этот
URL. Сценарии `auth.mode: disabled` и выключенной истории по-прежнему без
записей в таблицах диалогов.

Архитектура: импорт `sqlalchemy` / `alembic` запрещён в `ragkb/core/`;
в остальном пакете разрешён. Слайсовый `service.py` по-прежнему не тянет
чужие `features.*` (кроме уже существующего исключения bootstrap).

## Риски

Пустой Postgres на первой выкладке — потеря чатов и паролей из SQLite.
Осознанно.

Без Postgres локально не проходят тесты истории/входа и не стартует
`auth.mode: session`.

Смена head Alembic и выкладка должны выйти одним релизом, иначе `rag`
не поднимется.
