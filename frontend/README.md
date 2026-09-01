# Интерфейс базы знаний

SvelteKit-чат. Браузер к FastAPI не ходит: запросы идут в `/api/*` (BFF).

## Запуск

```
cd backend
uv sync --extra migrations --extra dev
# нужен Postgres и RAGKB_DATABASE_URL
alembic upgrade head
export RAGKB_AUTH_MODE=disabled
export RAGKB_HISTORY_ENABLED=false   # make backend: без форм и без Postgres
uv run uvicorn ragkb.platform.app:build --factory --port 8000

cd frontend
bun install
cp .env.example .env
bun run dev
```

## Переменные

| Переменная | Смысл |
|---|---|
| `RAGKB_BACKEND_URL` | Адрес бэкенда, по умолчанию `http://127.0.0.1:8000` |
| `RAGKB_DEV_USER` | Только `proxy`/локальный BFF. При `session` личность не даёт. В бою не задавать |
| `RAGKB_DEV_GROUPS` | Например `ragkb-admins` (режим `proxy`) |

`make up` / compose: `RAGKB_AUTH_MODE=session` — регистрация и вход в UI.
Angie на сервере не должен требовать OIDC на `/login`, `/register`, `/api/auth`.
Angie → `frontend:3000` → `rag:8000`.
