# ragkb — ориентиры для агента

Монорепозиторий: Python-сервис в `backend/`, SvelteKit в `frontend/`.
Пакет Python по-прежнему называется `ragkb`.

## Где что лежит

- Ядро поиска: `backend/ragkb/core/` — не импортирует `features/` и `platform/`.
- HTTP: вертикальные слайсы в `backend/ragkb/features/` (поиск, чат, индекс);
  auth уже в раскладке как в clustering: `domain/`, `services/`, `db/`, `api/`.
  Сборка — `backend/ragkb/platform/app.py` (`create_app`, `build`).
- История диалогов и локальные аккаунты: Postgres (SQLAlchemy async в
  `features/` и `platform/`). Схема — Alembic в `backend/migrations/`.
  Приложение схему не накатывает. URL: `RAGKB_DATABASE_URL`.
- Конфиг: `backend/config.yaml`, перекрывается `RAGKB_*`.
- Документы корпуса: `data/docs/` в корне репозитория.
- Контракт API и раскладка каталогов:
  `docs/superpowers/specs/2026-08-21-hexagonal-slices-design.md` и
  `docs/superpowers/specs/2026-08-31-backend-frontend-layout-design.md`.
  В первой спеке `web/` значит `frontend/`.

## Как запускать

Для `auth.mode: session` или включённой истории нужен `RAGKB_DATABASE_URL`
и `alembic upgrade head`. `make backend` — `RAGKB_AUTH_MODE=disabled` и
`RAGKB_HISTORY_ENABLED=false` (Postgres не нужен).

```
cd backend
uv sync --extra migrations --extra dev
alembic upgrade head
uv run uvicorn ragkb.platform.app:build --factory
cd ../frontend && bun run dev
```

CLI (`ragkb serve` / `index` / `ask`) нет. Индекс — `POST /index/rebuild`.
Тесты: `RAGKB_TEST_DATABASE_URL=… cd backend && uv run pytest`.

## Чего не делать

- Не возвращать HTML из FastAPI и не заводить второй UI рядом с `frontend/`.
- Не импортировать `sqlalchemy`/`alembic` в `backend/ragkb/core/`.
  SQLAlchemy можно в `features/` и `platform/`; Alembic — только
  `backend/migrations/`.
- Не ходить из браузера в FastAPI напрямую: только BFF `frontend/src/routes/api/`.
- Compose: `RAGKB_AUTH_MODE=session`, вход формами (`/login`, `/register`).
  `RAGKB_DEV_USER` сессию не заменяет. На сервере Angie не должен требовать
  OIDC на `/login`, `/register`, `/api/auth`. oauth2-proxy и Keycloak в стеке нет.
- LLM не поднимать в compose: OpenAI-совместимый HTTP (`RAGKB_LLM_URL`).
  Эмбеддинги в контейнере `rag` — HuggingFace (`sentence-transformers`,
  модель `BAAI/bge-m3`). Ollama в стеке нет.
- Исторические планы в `docs/superpowers/plans/` не переписывать под новую
  раскладку — это слепок прошлого.
