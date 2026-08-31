# Раскладка backend/ и frontend/

| | |
|---|---|
| Дата | 2026-08-31 |
| Версия | 1 |
| Статус | принято |
| Автор | Cursor Grok 4.6 |

## Зачем

Гексагональная спека режет пакет `ragkb` и выносит интерфейс в SvelteKit, но
оставляет Python в корне репозитория, а клиент — в `web/`. Нужны два явных
корня: сервис и интерфейс.

## Границы

**В работе:** имена каталогов и сервисов compose, точка входа uvicorn,
контексты сборки Docker.

**Вне работы:** поведение слайсов, контракт HTTP, Alembic, BFF, удаление CLI.
Всё это задано в
[2026-08-21-hexagonal-slices-design.md](2026-08-21-hexagonal-slices-design.md).
Там, где та спека пишет `web/`, читается `frontend/`. Там, где `pyproject.toml`
и `migrations/` «в корне репозитория», они лежат в `backend/` рядом с пакетом.

## Раскладка

```
backend/
  pyproject.toml  uv.lock  Dockerfile  alembic.ini  config.yaml
  ragkb/core  ragkb/platform  ragkb/features
  tests/  migrations/  examples/
frontend/
  package.json  bun.lock  Dockerfile  src/
data/  docs/  docker-compose.yml  .env.example
```

Имя Python-пакета остаётся `ragkb`. Импорты: `ragkb.core…`, `ragkb.platform…`,
`ragkb.features…`. Сборка: `uvicorn ragkb.platform.app:build --factory`.

Сервис приложения в compose называется `rag` (как раньше), контекст сборки —
`backend/`. Сервис интерфейса называется `frontend`, контекст — `frontend/`,
порт 3000. oauth2-proxy: `--upstream=http://frontend:3000`.

Тест правила зависимостей обходит `backend/ragkb/` и `backend/migrations/`.
