# Приложение без аккаунтов и истории — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Удалить аккаунты, авторизацию и историю, сохранив открытый чат и управление корпусом.

**Architecture:** Новый сценарий AskService вызывает AnswerEngine без истории и возвращает NDJSON. Браузер хранит только текущую ленту в памяти; Storage обслуживает только реестр документов. Старые миграции и данные остаются, но приложение больше не использует таблицы аккаунтов и переписки.

**Tech Stack:** Python, FastAPI, SQLAlchemy, Alembic, pytest; Svelte 5, SvelteKit, Bun.

**Spec:** `docs/superpowers/specs/2026-09-21-without-auth-and-history-design.md`

## Global Constraints

- Браузер обращается к FastAPI только через BFF.
- Каждый вопрос независим, сервер не хранит переписку даже в памяти.
- Реестр документов, файлы и индекс сохраняются.
- При подключённой БД индекс строится только по принятым документам.
- Существующие данные не стираются автоматически; старые миграции и планы не переписываются.
- Слои api/core/db/domain/services сохраняются, зависимости проверяются архитектурными тестами.
- Удаляются оценки ответов, привязанные к сохраняемым сообщениям.

## Review Focus

1. Вопрос из пробелов отклоняется до открытия NDJSON-потока (задача 1).
2. Исключение до первого токена даёт резервный ответ, после первого — truncated и done (задача 1).
3. Повторные вопросы от разных клиентов не разделяют серверный контекст (задача 1).
4. Существующая БД после обновления сохраняет corpus_documents и старые данные (задача 2).
5. Очистка чата и повтор ответа не позволяют запоздалому потоку изменить новую ленту (задача 3).

## Task 1: Самостоятельный поток ответа

**Files:** создать `backend/ragkb/services/ask.py`, `backend/ragkb/api/schemas/ask.py`,
`backend/ragkb/api/routes/ask.py`, `backend/tests/test_ask.py`; изменить
`backend/ragkb/api/router.py`, `backend/ragkb/api/deps/services.py`.

**Interfaces:** AskService(engine, resolve_model), где engine — фабрика AnswerEngine,
resolve_model — существующий метод каталога. Метод
`stream(question, *, model=None, top_k=None, expand=False)` возвращает AsyncIterator[str].
HTTP POST `/api/v1/ask` не принимает идентификатор диалога или пользователя.

- [ ] Добавить тест доступности без cookie и формата результата:

```python
def test_ask_without_identity(client):
    import json
    response = client.post('/api/v1/ask', json={'question': 'Сколько дней отпуска?'})
    assert response.status_code == 200
    events = [json.loads(line) for line in response.text.splitlines()]
    assert events[-1]['type'] == 'done'
    assert any(e['type'] == 'token' for e in events)
    assert 'conversation_id' not in events[-1]
    assert 'message_id' not in events[-1]
    assert 'set-cookie' not in response.headers

def test_blank_question(client):
    assert client.post('/api/v1/ask', json={'question': '   '}).status_code == 422
```

- [ ] Запустить `.venv/bin/pytest tests/test_ask.py`; до реализации новый маршрут отвечает 404.
  Тестовые фикстуры переключить на временную SQLite в задаче 2; до этого использовать
  отдельную тестовую БД, никогда существующую пользовательскую.
- [ ] Создать схему с trim вопроса, min_length=2 и диапазоном top_k 1–20.
  Неизвестную модель преобразовывать из ValueError в InvalidRequest до открытия потока.
- [ ] Перенести генерацию token/done из ChatConversationsService в AskService,
  удалив чтение/запись истории, пользователя, conversation_id и message_id.
  Вызов ядра:

```python
hits, tokens = engine.stream_answer(
    question, top_k=top_k, history=None, expand=expand, model=resolved
)
```

- [ ] Сохранить cited_sources, fallback_text и предупреждения. При обрыве убрать
  слова о сохранении ответа. Проверить поддельным движком три генератора:
  обычные токены; исключение до первого токена; токен и исключение.
  Во всех случаях последнее событие — done; truncated истинно только в третьем.
- [ ] Проверить два запроса с разными вопросами: движок получает history=None
  оба раза; отсутствуют обращения к репозиториям и Set-Cookie.
- [ ] Повторить тесты ask и существующие тесты потока ядра.

## Task 2: Удаление серверных аккаунтов и истории

**Files:** изменить `backend/ragkb/main.py`, `backend/ragkb/core/config.py`,
`backend/ragkb/core/database.py`, `backend/ragkb/db/storage.py`, `backend/ragkb/db/models.py`,
`backend/ragkb/domain/entities.py`, `backend/ragkb/domain/ports.py`,
`backend/ragkb/api/router.py`, `backend/ragkb/api/deps/services.py`,
`backend/ragkb/services/bootstrap.py`, `backend/ragkb/services/telemetry.py`,
`backend/ragkb/api/routes/{bootstrap,documents,index,models,organization,search,telemetry,admin}.py`,
`backend/migrations/env.py`, `backend/tests/{helpers,conftest,test_api,test_documents,test_index,test_architecture}.py`.

Удалить API `auths.py`, `users.py`, `chat_conversations.py`, зависимость `deps/auth.py`,
схемы `auth.py`, `chat_conversations.py`, `feedback.py`; сервисы `auth.py`,
`admin_users.py`, `chat_conversations.py`, `chat_cache.py`, `chat_sources.py`, `feedback.py`;
репозитории `auth.py`, `postgres_history.py`, `ephemeral_history.py`, `feedback.py`;
`core/security.py`, `scripts/ensure_admin.py` и тесты исключительно удаляемых сценариев.

**Interfaces:** BootstrapService.app_start(session_id) не принимает User;
ответ содержит session_id, version, organization, models, index, без аккаунта и диалогов.
Storage предоставляет corpus, ready(), ensure(), dispose(); подключается только при наличии database_url.

- [ ] Добавить параметризованный тест отсутствия старых маршрутов:

```python
@pytest.mark.parametrize('method,path', [
    ('POST', '/api/v1/auths/signin'),
    ('GET', '/api/v1/auths/me'),
    ('GET', '/api/v1/admin/users'),
    ('POST', '/api/v1/organization/acme/chat_conversations'),
])
def test_removed_routes(client, method, path):
    assert client.request(method, path, json={}).status_code == 404
```

- [ ] Запустить новые тесты и убедиться, что существующие маршруты ещё доступны — тест красный.
- [ ] Удалить перечисленные компоненты и их импорты. Снять current_user/require_admin
  со всех оставшихся API. В управлении документами передавать пустое uploaded_by;
  убрать упоминания личности в журналировании. В admin оставить сведения об организации
  и существующую заглушку отчётов, убрать ссылки на пользователей и оценки.
- [ ] Удалить AuthConfig, HistoryConfig, их env-перекрытия и app.state.auth.
  Удалить из сущностей/портов аккаунты, сессии, историю, оценки и утилиты заголовков.
  Сохранить сущность и порт реестра корпуса, EventSink и необходимые порты ядра.
- [ ] Storage создаёт только PostgresCorpusDocuments. ready проверяет ревизию БД
  при подключении; отсутствие database_url означает corpus=None.
  В models.py оставить CorpusDocumentRow. В migrations/env.py импортировать его
  вместо UserRow. Исторические файлы migrations/versions не менять.
- [ ] Изолировать тестовую SQLite в tmp_path: применять Alembic до теста и передавать
  URL через cfg.database_url. Удалить глобальную очистку пользовательских таблиц
  и зависимость обычного набора тестов от внешнего Postgres.
- [ ] Проверить upgrade head на временной БД и повторный запуск миграции; создать
  старые записи средствами SQL, запустить новый Storage и убедиться, что они сохранились.
  Проверить загрузку/принятие/удаление документов и ограничение индекса реестром.
- [ ] Проверить bootstrap без пользователя и историю-независимый поиск без БД.
  Выполнить pytest для API, документов, индекса, архитектуры и ask.

## Task 3: Чат без входа и сохранённых диалогов

**Files:** изменить `frontend/src/lib/server/backend.js`, `frontend/src/lib/chat.svelte.js`,
`frontend/src/lib/Chat.svelte`, `frontend/src/lib/components/chat/{ChatComposer,Message}.svelte`,
`frontend/src/routes/+layout.svelte`, `frontend/src/routes/new/+page.svelte`,
`frontend/src/routes/api/ask/+server.js`, `frontend/src/routes/admin/{+layout,+page}.svelte`.
Удалить `frontend/src/hooks.server.js`, страницы `login`, `register`, `profile`,
`chat/[id]`, `admin/users`, `admin/feedback`, BFF `api/auths`, `api/conversations`,
`api/admin/users`, `api/admin/feedback`. Проверить редирект `/chat` на `/new`.

**Interfaces:** chat хранит messages, question, models, model, organization, version,
busy, fatal и состояние инициализации. sendQuestion() вызывает BFF `/api/ask`;
reset() очищает ленту, regenerate() повторяет последний вопрос новым запросом.

- [ ] BFF POST /api/ask напрямую проксирует JSON на POST /api/v1/ask и возвращает
  upstream.body без буферизации. Удалить создание диалога и x-conversation-id.
  Сохранить обработку HTTP-ошибок и недоступного backend.
- [ ] Из backend.js удалить identity(), proxyAuth() и передачу cookie/заголовков
  пользователя; оставить JSON-заголовки и существующую обработку multipart.
- [ ] Удалить из состояния и функций клиента пользовательские поля, историю,
  CRUD диалогов, оценки, onCreated и переходы на /chat/{id}. NDJSON-парсер
  сохраняет токены и done, но не идентификаторы серверных сообщений.
- [ ] Для нового вопроса отправлять только question/model/top_k/expand.
  Пока busy=true, блокировать очистку и повтор запроса; при ошибке сбрасывать busy
  в finally. Повторный ответ заменяет последний ответ новым потоком по последнему
  вопросу без обращения к серверной истории.
- [ ] В layout удалить боковую историю, меню профиля/выхода и условия прав.
  Сохранить выбор модели, оформление и тему; сделать ссылки на документы и
  управление общедоступными. Кнопку нового диалога заменить «Очистить чат».
- [ ] В Message удалить оценки и связанные формы. Сохранить копирование,
  источники и повтор последнего ответа. Удалить onCreated из Chat и Composer.
- [ ] Выполнить `bun run check` и `bun run build`.
- [ ] Проверить в браузере: вход без cookie; вопрос и источники; повтор ответа;
  блокировку очистки во время потока; очистку после завершения; пустую ленту
  после обновления страницы; отсутствие данных другой вкладки; открытие документов.

## Task 4: Запуск, документация и итоговая проверка

**Files:** `docker-compose.yml`, `.github/workflows/deploy.yml`, `deploy.sh`, `Makefile`,
`.env.example`, `frontend/.env.example`, `backend/pyproject.toml`, `backend/uv.lock`,
`README.md`, `AGENTS.md` и согласованная спецификация.

**Interfaces:** Compose запускает postgres → migrate → rag → frontend;
локальный backend запускается без auth/history env. БД нужна только реестру.

- [ ] Удалить сервис ensure-admin и зависимость rag от него; связать rag с migrate.
  Удалить ADMIN_LOGIN/ADMIN_PASSWORD, auth/history/dev-user env из примеров и запуска.
  Удалить argon2-cffi, если других потребителей нет; обновить lock через uv lock.
- [ ] Обновить команды Makefile и deployment; документацию API и локального старта.
  В AGENTS.md заменить устаревшие ограничения про вход и аккаунты согласованной схемой.
  Явно указать отсутствие сохранения/контекста диалога и сохранение старых данных в БД.
- [ ] Проверить остатки рабочего кода:

```sh
rg -n 'current_user|require_admin|ensure_admin|ADMIN_LOGIN|ADMIN_PASSWORD|cfg\.auth|cfg\.history|chat_conversations|proxyAuth' backend/ragkb frontend/src docker-compose.yml Makefile .github
```

  Ожидается отсутствие совпадений; исторические миграции, планы и спецификации
  не входят в эту проверку.
- [ ] Выполнить полный backend pytest, frontend check/build и `docker compose config --quiet`
  с тестовыми env-значениями, если установлен Docker. Проверить git diff --check.
- [ ] Поднять сервисы на loopback, проверить health, bootstrap, документы и ask через BFF;
  старые маршруты возвращают 404. После smoke-проверки остановить запущенные процессы.
- [ ] Проверить итоговый diff на удаление только согласованных сценариев, записать
  результаты проверок и ограничения окружения. Обновить статус спецификации.

## Проверка плана

Все разделы спецификации покрыты задачами 1–4. Риски Review Focus включены в
соответствующие задачи. Существующие данные не уничтожаются; миграции не откатываются.
Предлагаемый способ выполнения — последовательно в текущей задаче: изменения
backend, BFF и UI используют один новый контракт ответа и тесно связаны.
