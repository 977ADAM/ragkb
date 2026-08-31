# ragkb — ориентиры для агента

Монорепозиторий: Python-сервис в `backend/`, SvelteKit в `frontend/`.
Пакет Python по-прежнему называется `ragkb`.

## Где что лежит

- Ядро поиска: `backend/ragkb/core/` — не импортирует `features/` и `platform/`.
- HTTP: вертикальные слайсы в `backend/ragkb/features/`; сборка приложения —
  `backend/ragkb/platform/app.py` (`create_app`, `build`).
- История диалогов: SQLite-запросы в слайсе, схема — Alembic в
  `backend/migrations/`. Приложение схему не накатывает.
- Конфиг: `backend/config.yaml`, перекрывается `RAGKB_*`.
- Документы корпуса: `data/docs/` в корне репозитория.
- Контракт API и раскладка каталогов:
  `docs/superpowers/specs/2026-08-21-hexagonal-slices-design.md` и
  `docs/superpowers/specs/2026-08-31-backend-frontend-layout-design.md`.
  В первой спеке `web/` значит `frontend/`.

## Как запускать

```
cd backend
uv sync --extra migrations --extra dev
alembic upgrade head
uv run uvicorn ragkb.platform.app:build --factory
cd ../frontend && bun run dev
```

CLI (`ragkb serve` / `index` / `ask`) нет. Индекс — `POST /index/rebuild`.
Тесты: `cd backend && uv run pytest`.

## Чего не делать

- Не возвращать HTML из FastAPI и не заводить второй UI рядом с `frontend/`.
- Не импортировать `sqlalchemy`/`alembic` вне `backend/migrations/`.
- Не ходить из браузера в FastAPI напрямую: только BFF `frontend/src/routes/api/`.
- В боевом compose не задавать `RAGKB_DEV_USER` (вход — Angie, заголовки
  `X-Forwarded-*`). oauth2-proxy в стеке нет.
- LLM не поднимать в compose: OpenAI-совместимый HTTP (`RAGKB_LLM_URL`).
  Эмбеддинги в контейнере `rag` — HuggingFace (`sentence-transformers`,
  модель `BAAI/bge-m3`). Ollama в стеке нет.
- Исторические планы в `docs/superpowers/plans/` не переписывать под новую
  раскладку — это слепок прошлого.
