# ragkb — ориентиры для агента

Монорепозиторий: Python-сервис в `backend/`, SvelteKit в `frontend/`.
Пакет Python называется `ragkb`.

## Архитектура

Пять каталогов в `backend/ragkb/`:

- `api/` — FastAPI: роутеры, схемы, Depends-фабрики и HTTP-ошибки.
- `core/` — LangChain-ядро: `documents.py` (секции и чанки), `vectorstore.py`,
  `retrieval.py`, `pipeline.py` (LCEL-цепочка), конфиг, движок БД и ошибки.
  Не импортирует `api/`, `db/`, `domain/`, `services/` и не зависит от FastAPI.
- `db/` — SQLAlchemy-модель и адаптер реестра документов.
- `domain/` — чистые сущности и порты без SQLAlchemy/pydantic/FastAPI.
- `services/` — сценарии через порты, без FastAPI, SQLAlchemy, LangChain,
  пайплайна и каталогов моделей.

`main.py` собирает Storage, EngineCache, ConfigIndex, каталог моделей и sink
телеметрии в app.state. Класса Container нет.

## Чат и документы

- Авторизации, аккаунтов, ролей и истории нет. Сайт сразу открывает чат.
  Управление документами и индексацией доступно всем посетителям.
- POST `/api/v1/ask` — независимый вопрос. NDJSON: token, затем done
  с источниками и truncated. Сервер не сохраняет переписку даже в памяти.
  Генерация обязательна: без `RAGKB_LLM_URL` запрос отклоняется с 503 до
  открытия потока, экстрактивного ответа нет.
- Текущая лента хранится только в памяти браузерной страницы. Повтор ответа
  — новый запрос с тем же вопросом. Оценок и серверных идентификаторов сообщений нет.
- Браузер обращается только к BFF `frontend/src/routes/api/`:
  `/api/…` → FastAPI `/api/v1/…`. GET `/health` без версии.
- Реестр `corpus_documents` — единственный источник документов: попасть в
  корпус можно только загрузкой через `/admin/documents`. Каталог `data/docs`
  не обходится (`loaders.discover` удалён), файл мимо интерфейса не
  индексируется и в списке не виден. Приёма файлов из каталога нет.
  Без БД загрузка, удаление и пересборка отклоняются с 400 и подсказкой
  задать `RAGKB_DATABASE_URL`.
- Postgres (Compose) или SQLite (локально) нужны только реестру документов.
  URL — `RAGKB_DATABASE_URL`. Миграции — `backend/migrations/`;
  приложение не накатывает схему само.
- Миграция одна — `0001_corpus_documents`. Схему аккаунтов и переписки она
  не создаёт, но и не удаляет: старые таблицы в уже существующих базах
  остаются нетронутыми. Такую базу помечают
  `alembic stamp --purge 0001_corpus_documents` — без `--purge` не выйдет,
  прежней ревизии больше нет в каталоге версий. Не уничтожать существующие
  данные автоматически.
- Конфиг — `backend/ragkb/core/config.py`, перекрывается окружением `RAGKB_*`,
  а поверх него — файл настроек со страницы `/admin/settings`
  (`data/settings.json`, путь задаёт `RAGKB_SETTINGS_FILE`). Каталог полей,
  которые вообще можно править, — `backend/ragkb/core/settings.py`; страница
  рисуется по ответу `GET /api/v1/admin/settings` и не знает про `Settings`.
- Актуальное решение: `docs/superpowers/specs/2026-09-21-without-auth-and-history-design.md`.
  Прежние документы об авторизации и истории описывают старый контракт.

Тесты backend: `cd backend && uv run pytest` (временная SQLite, внешняя БД и
Ollama не нужны: тесты подставляют бэкенд `fake` и `InMemoryVectorStore`,
модель ответа — `ScriptedChatModel` из `tests/helpers.py`).
Frontend: `cd frontend && bun test && bun run check && bun run build`.

## Ограничения

- Не возвращать HTML из FastAPI и не заводить второй UI рядом с frontend.
- SQLAlchemy — в db/, исключение core/database.py владеет движком и Base.
  Alembic — только backend/migrations/.
- В Compose нет ensure-admin, oauth2-proxy, Keycloak, сервиса Ollama и
  LLM-сервера. Angie проксирует frontend без прежней проверки входа.
- Эмбеддинги считает Ollama вне образа: `RAGKB_EMBEDDING_URL`
  (`http://127.0.0.1:11434` локально, `http://host.docker.internal:11434` из
  контейнера), модель по умолчанию `qwen3-embedding:0.6b`. В образе rag нет
  torch и sentence-transformers; бэкенд `fake` (детерминированные векторы)
  нужен только тестам. Модель и её размерность попадают в манифест: смена
  требует переиндексации.
  Решение: `docs/superpowers/specs/2026-09-21-ollama-embeddings-design.md`.
- Генерация — OpenAI-совместимый HTTP (`RAGKB_LLM_URL`) через
  `langchain_openai.ChatOpenAI`; подойдёт и Ollama (её корень с `/v1`).
- Ядро собрано на LangChain 1.x (`langchain-core`, `langchain-classic`,
  `langchain-text-splitters`, `langchain-ollama`, `langchain-chroma`,
  `langchain-openai`, `rank-bm25`). `langchain-community` не используем: он
  объявлен устаревшим. LangChain живёт только в `core/` — `api/` и `services/`
  видят порты, это проверяет `tests/test_architecture.py`.
  Решение: `docs/superpowers/specs/2026-09-21-langchain-core-design.md`.
- Каталоги данных (`docs_dir`, `index_dir`, `settings_file`, `logging.dir`)
  по умолчанию относительные и считаются от рабочего каталога процесса: сервис
  запускают из корня репозитория (`make api` добавляет `--app-dir backend`,
  не меняя каталог). Эффективные пути видны в журнале при старте, в
  `/api/v1/status` и на странице настроек. В манифесте индекса лежат пути к
  исходным файлам, поэтому смена каталога документов требует пересборки.
- CLI serve/index/ask нет. Индекс перестраивается через API и интерфейс.
- Исторические планы не переписывать под новую архитектуру. Цепочка миграций
  намеренно сведена к одной начальной ревизии — прежние восемь файлов
  восстанавливать не нужно.
