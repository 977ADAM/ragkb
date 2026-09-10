# ragkb — ориентиры для агента

Монорепозиторий: Python-сервис в `backend/`, SvelteKit в `frontend/`.
Пакет Python по-прежнему называется `ragkb`.

## Где что лежит

Пять каталогов в `backend/ragkb/` — раскладка по слоям, как в clustering:

- `api/` — FastAPI: роутеры, схемы, Depends-фабрики, HTTP-хендлер ошибок.
- `core/` — ядро поиска и генерации; конфиг, движок БД (`database.py`),
  доменные ошибки (`errors.py`). Не импортирует `api/`, `db/`, `domain/`,
  `services/` и не знает FastAPI (кроме исключений в сигнатурах нет).
- `db/` — SQLAlchemy-модели и адаптеры хранения: `models.py`, `repos/`
  (Postgres и память: `PostgresAccounts`, `PostgresHistory`,
  `EphemeralHistory`).
- `domain/` — чистые сущности и порты без SQLAlchemy/pydantic/FastAPI.
- `services/` — сценарии (use cases) без FastAPI, SQLAlchemy, пайплайна и
  каталогов моделей. Данные и LLM приходят через порты
  (`domain/ports.py`, `core/ports.py`).
- Сборка: `backend/ragkb/main.py` кладёт на
  `app.state` отдельные объекты: `db/storage.py`, `core/engine.py`,
  `core/index.py`, `core/catalogs/`. Класса `Container` нет.

- История диалогов и локальные аккаунты: Postgres (SQLAlchemy async в
  `db/`). Схема — Alembic в `backend/migrations/`. Приложение схему не
  накатывает. URL: `RAGKB_DATABASE_URL`.
- Конфиг: `backend/config.yaml`, перекрывается `RAGKB_*`.
- Документы корпуса: `data/docs/` в корне репозитория. В базу знаний они
  попадают **только через интерфейс** `/admin/documents`: реестр в Postgres
  (`corpus_documents`, `db/repos/corpus_documents.py`) — источник истины, и
  индекс собирается по нему. Файл в каталоге мимо интерфейса не индексируется,
  пока админ не нажмёт «Принять». Без БД реестра нет и индексируется весь
  каталог (страница об этом предупреждает).
- Контракт API: `docs/superpowers/specs/2026-08-21-hexagonal-slices-design.md`
  (там `web/` значит `frontend/`; каталоги `features/`/`platform/` в тексте
  — историческая раскладка, актуальную смотри в этом файле и в README).

## Как запускать

Для `auth.mode: session` или включённой истории нужен `RAGKB_DATABASE_URL`
и `alembic upgrade head`. `make backend` — SQLite `data/ragkb.sqlite3`,
`auth.mode: session` (Postgres не нужен). Compose остаётся на Postgres.

```
cd backend
uv sync --extra migrations --extra dev
alembic upgrade head
uv run uvicorn ragkb.main:app
cd ../frontend && bun run dev
```

CLI (`ragkb serve` / `index` / `ask`) нет. Индекс — `POST /api/v1/index/rebuild`.
Тесты: `RAGKB_TEST_DATABASE_URL=… cd backend && uv run pytest`.

## Чего не делать

- Не возвращать HTML из FastAPI и не заводить второй UI рядом с `frontend/`.
- Не импортировать `sqlalchemy`/`alembic` в `backend/ragkb/core/` (кроме
  `core/database.py`, который владеет движком и `Base`).
  SQLAlchemy — только в `backend/ragkb/db/`; Alembic — только
  `backend/migrations/`.
- Не ходить из браузера в FastAPI напрямую: только BFF `frontend/src/routes/api/`
  (BFF `/api/…` → FastAPI `/api/v1/…`; `GET /health` без версии).
- Compose: `RAGKB_AUTH_MODE=session`, вход формой `/login` (учётку создаёт
  админ на `/admin/users`). `/register` остаётся публичной страницей-пояснением.
  `RAGKB_DEV_USER` сессию не заменяет. На сервере Angie не должен требовать
  OIDC на `/login`, `/register`, `/api/auths`. oauth2-proxy и Keycloak в стеке нет.
- LLM не поднимать в compose: OpenAI-совместимый HTTP (`RAGKB_LLM_URL`).
  Эмбеддинги в контейнере `rag` — HuggingFace (`sentence-transformers`,
  модель `BAAI/bge-m3`). Ollama в стеке нет.
- Исторические планы в `docs/superpowers/plans/` не переписывать под новую
  раскладку — это слепок прошлого.
