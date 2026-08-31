# Интерфейс базы знаний

SvelteKit-чат. Браузер к FastAPI не ходит: запросы идут в `/api/*` (BFF).

## Запуск

```
cd backend
uv sync --extra migrations --extra dev
alembic upgrade head
export RAGKB_AUTH_MODE=disabled
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
| `RAGKB_DEV_USER` | Логин без oauth2-proxy. В бою не задавать |
| `RAGKB_DEV_GROUPS` | Например `ragkb-admins` |

В compose `RAGKB_DEV_USER` не задаётся. Proxy → `frontend:3000` → `rag:8000`.
