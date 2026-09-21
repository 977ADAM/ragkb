# ragkb — ориентиры для агента

Монорепозиторий: Python-сервис в `backend/`, SvelteKit в `frontend/`.
Пакет Python называется `ragkb`.

## Архитектура

Пять каталогов в `backend/ragkb/`:

- `api/` — FastAPI: роутеры, схемы, Depends-фабрики и HTTP-ошибки.
- `core/` — поиск, генерация, конфиг, движок БД и ошибки. Не импортирует
  `api/`, `db/`, `domain/`, `services/` и не зависит от FastAPI.
- `db/` — SQLAlchemy-модель и адаптер реестра документов.
- `domain/` — чистые сущности и порты без SQLAlchemy/pydantic/FastAPI.
- `services/` — сценарии через порты, без FastAPI, SQLAlchemy, пайплайна
  и каталогов моделей.

`main.py` собирает Storage, EngineCache, ConfigIndex, каталог моделей и sink
телеметрии в app.state. Класса Container нет.

## Чат и документы

- Авторизации, аккаунтов, ролей и истории нет. Сайт сразу открывает чат.
  Управление документами и индексацией доступно всем посетителям.
- POST `/api/v1/ask` — независимый вопрос. NDJSON: token, затем done
  с источниками и truncated. Сервер не сохраняет переписку даже в памяти.
- Текущая лента хранится только в памяти браузерной страницы. Повтор ответа
  — новый запрос с тем же вопросом. Оценок и серверных идентификаторов сообщений нет.
- Браузер обращается только к BFF `frontend/src/routes/api/`:
  `/api/…` → FastAPI `/api/v1/…`. GET `/health` без версии.
- Реестр `corpus_documents` — источник истины при подключённой БД. Файлы
  в `data/docs/` принимаются через `/admin/documents`. Файл мимо интерфейса
  не индексируется до принятия. Без БД индексируется весь каталог с предупреждением UI.
- Postgres (Compose) или SQLite (локально) нужны только реестру документов.
  URL — `RAGKB_DATABASE_URL`. Миграции — `backend/migrations/`;
  приложение не накатывает схему само.
- Миграция одна — `0001_corpus_documents`. Схему аккаунтов и переписки она
  не создаёт, но и не удаляет: старые таблицы в уже существующих базах
  остаются нетронутыми. Такую базу помечают
  `alembic stamp --purge 0001_corpus_documents` — без `--purge` не выйдет,
  прежней ревизии больше нет в каталоге версий. Не уничтожать существующие
  данные автоматически.
- Конфиг — `backend/ragkb/core/config.py`, перекрывается окружением `RAGKB_*`.
- Актуальное решение: `docs/superpowers/specs/2026-09-21-without-auth-and-history-design.md`.
  Прежние документы об авторизации и истории описывают старый контракт.

## Запуск и проверки

Из корня: `make sync`, `make sync-frontend`, затем задать URL БД и пути
RAGKB_DOCS_DIR/RAGKB_INDEX_DIR. `make migrate`, `make api`, в другом терминале
`make frontend`. `make backend` — псевдоним `make api`.

Тесты backend: `cd backend && uv run pytest` (временная SQLite, внешняя БД не нужна).
Frontend: `cd frontend && bun test && bun run check && bun run build`.

## Ограничения

- Не возвращать HTML из FastAPI и не заводить второй UI рядом с frontend.
- SQLAlchemy — в db/, исключение core/database.py владеет движком и Base.
  Alembic — только backend/migrations/.
- В Compose нет ensure-admin, oauth2-proxy, Keycloak, Ollama и LLM-сервера.
  Angie проксирует frontend без прежней проверки входа.
- LLM — OpenAI-совместимый HTTP (`RAGKB_LLM_URL`). Эмбеддинги в контейнере
  rag — sentence-transformers, модель BAAI/bge-m3.
- CLI serve/index/ask нет. Индекс перестраивается через API и интерфейс.
- Исторические планы не переписывать под новую архитектуру. Цепочка миграций
  намеренно сведена к одной начальной ревизии — прежние восемь файлов
  восстанавливать не нужно.
