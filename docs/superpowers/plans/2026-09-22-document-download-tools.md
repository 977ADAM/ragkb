# Document Download Tools Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans for inline execution or superpowers:subagent-driven-development if the user selects delegated execution. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Чат выдаёт проверенные ссылки на оригиналы разрешённых документов через настоящий tool calling, сохраняя поиск и цитаты по всем документам.

**Architecture:** Реестр владеет идентификаторами и разрешениями; прикладной слой разрешает скачивание и готовит кандидатов. Core выполняет цикл LangChain через внедрённый асинхронный callback, не импортируя верхние слои. FastAPI передаёт файл, BFF ограничивает скачивания и проксирует поток, Svelte показывает вложения и управление флагом.

**Tech Stack:** Существующие Python/FastAPI/Pydantic, SQLAlchemy/Alembic, LangChain/ChatOpenAI, Svelte 5/SvelteKit 2 и Bun. Новые серверы, Hono, Redis и библиотеки UI не требуются.

**Spec:** [Согласованная спецификация](../specs/2026-09-22-document-download-tools-design.md).

## Global Constraints

- Управление намеренно открыто всем; не вводить авторизацию и роли.
- `download_allowed` по умолчанию false, включая существующие записи.
- DOCX базы знаний остаётся источником ответов и фрагментов.
- Только зарегистрированные документы; не обходить data/docs и не публиковать static-каталог.
- Все модели поддерживают инструменты; не заменять tool calling разбором ссылок в тексте.
- Каждый вопрос независим; история tool calls существует только в текущем запросе.
- LangChain только в core; core не импортирует api/db/domain/services.
- Схемой БД владеет Alembic; новую 0002 добавить после 0001, старые таблицы не трогать.
- Скачивание идёт через BFF; модель не определяет файловые пути и URL.
- Предлагаемые лимиты: 10 запросов/минуту, burst 3, две одновременные передачи на IP.
- Логи не содержат вопросы, содержимое файлов или секреты; IP не считается личностью.
- Не менять существующие разрешения на пользовательских данных автоматически.

## Review Focus

1. Отзыв разрешения между tool call и GET: старая карточка должна получить 404 (задачи 2, 6).
2. Замена файла и повторная загрузка: ID сохраняется только при замене существующей записи, разрешение не наследуется молча (задача 1).
3. Медленный клиент/отмена: поток не буферизуется BFF, соединение backend и слот limiter освобождаются (задача 3).
4. Неоднозначные HTML5/Mobile HTML5 и MediaText/Premium: не выбирать файл по первому частичному совпадению (задача 4).
5. Отсутствие БД: обычный доступный RAG-ответ не должен ломаться из-за отсутствия каталога вложений (задача 5).

## Подготовка и структура файлов

Перед реализацией прочитать spec и AGENTS.md, проверить рабочее дерево. Изоляцию
выполнять по using-git-worktrees на этапе реализации, не во время написания плана.
Не переносить реальные файлы корпуса и настройки в тестовую среду.

Новые единицы ответственности:

| Файл | Назначение |
|---|---|
| `backend/migrations/versions/0002_document_downloads.py` | ID и разрешение существующих документов |
| `backend/ragkb/services/downloads.py` | Разрешение оригиналов и изменение флага |
| `backend/ragkb/services/download_candidates.py` | Привязка источников к реестру и кандидаты по имени |
| `backend/ragkb/api/schemas/downloads.py` | HTTP DTO разрешений и вложений |
| `backend/ragkb/api/routes/downloads.py` | PATCH разрешения, GET/HEAD оригинала |
| `backend/ragkb/core/tool_answers.py` | Ограниченный цикл вызова инструмента |
| `backend/ragkb/core/answer_events.py` | Независимые от LangChain типы событий и callback |
| `frontend/src/lib/server/download-limiter.js` | Частота и параллелизм по IP |
| `frontend/src/lib/server/download-proxy.js` | Передача тела с учётом отмены и аудита |
| `frontend/src/lib/server/request-context.js` | Доверенный request ID и контекст внешнего запроса |
| `frontend/src/lib/components/chat/Attachments.svelte` | Карточки и ошибки скачивания |
| `frontend/src/lib/download.js` | Клиентское скачивание оригинала с обработкой HTTP-ошибок |

Изменения существующего кода перечислены в каждой задаче. Порядок задач:
1 → 2 → 3 → 4 → 5 → 6 → 7. Отдельные коммиты позволяют проверять каждый контракт.

## Task 1: Расширить реестр без потери данных

**Files:** новая миграция; изменить `backend/ragkb/domain/entities.py`,
`domain/ports.py`, `db/models.py`, `db/repos/corpus_documents.py`,
`core/database.py`, `services/documents.py`, `tests/helpers.py`;
создать `backend/tests/test_download_registry.py`.

**Interfaces:**

```python
# CorpusDocument: новые поля; имя остаётся primary key таблицы.
document_id: str
download_allowed: bool = False

# DocumentRegistry и оба адаптера (SQLAlchemy и MemoryRegistry):
async def get_by_id(self, document_id: str) -> CorpusDocument | None: ...
async def set_download_allowed(
    self, document_id: str, allowed: bool
) -> tuple[bool, CorpusDocument] | None: ...  # старое значение + сохранённая запись
# record(..., download_allowed: bool = False) -> None
# DocumentsService.upload(..., download_allowed: bool = False) -> dict
```

- [x] Написать тест на MemoryRegistry и повторить семантику на временной SQLite:

```python
async def test_replace_resets_permission_and_keeps_id():
    registry = MemoryRegistry()
    await registry.record('spec.pdf', download_allowed=True)
    original = (await registry.list_all())[0]
    await registry.record('spec.pdf')
    replaced = await registry.get_by_id(original.document_id)
    assert replaced is not None
    assert replaced.document_id == original.document_id
    assert replaced.download_allowed is False
    await registry.forget('spec.pdf')
    await registry.record('spec.pdf')
    assert (await registry.list_all())[0].document_id != original.document_id
```

- [x] Запустить `cd backend && uv run pytest tests/test_download_registry.py -q`;
  подтвердить падение из-за отсутствующего контракта, а не настройки окружения.
- [x] Добавить миграцию: nullable ID → заполнение UUID для каждой строки →
  unique/not-null; boolean с server_default false. SQLite использовать через
  Alembic batch_alter_table, Postgres — совместимые операции Alembic.
  Переход downgrade удаляет только новые поля/индекс; не удаляет документы.

```python
revision = '0002_document_downloads'
down_revision = '0001_corpus_documents'
# UUID генерируется на каждую строку, не одним значением server_default.
for name in connection.execute(sa.text('SELECT name FROM corpus_documents')).scalars():
    connection.execute(
        sa.text('UPDATE corpus_documents SET document_id=:id WHERE name=:name'),
        {'id': str(uuid4()), 'name': name},
    )
```

- [x] Обновить EXPECTED_REVISION. Сохранять ID при record существующего имени,
  явно сохранять download_allowed, новое имя получает UUID. Изменение флага
  возвращает старое значение из той же транзакции; не вычислять его до записи
  отдельным незащищённым чтением. SQL-адаптер и MemoryRegistry равнозначны.
- [x] Дописать миграционные тесты: БД на 0001 с двумя документами и посторонней
  таблицей; upgrade сохраняет данные, создаёт разные ID и false; повторный
  upgrade безопасен; downgrade/upgrade сохраняет прежние поля. Проверить
  `assert_revision` после миграции. Не считать сохранение ID после downgrade
  требованием: откат удаляет новый столбец.
- [x] Запустить `uv run pytest tests/test_download_registry.py tests/test_documents.py tests/test_architecture.py -q`.
- [x] Зафиксировать только файлы задачи: `feat: add document download permissions to registry`.

## Task 2: Выдавать оригинал только через проверенный API

**Files:** создать `services/downloads.py`, `api/schemas/downloads.py`,
`api/routes/downloads.py`, `tests/test_downloads.py`; изменить `api/router.py`,
`api/deps/services.py`, `api/routes/documents.py`, `services/documents.py`.

**Interfaces:**

```python
@dataclass(frozen=True)
class DownloadDescriptor:  # services/downloads.py, наружу путь не сериализуется
    document_id: str
    filename: str
    path: Path
    media_type: str
    size: int

class DownloadsService:
    def __init__(self, docs_dir: Path, registry: DocumentRegistry | None): ...
    async def resolve(self, document_id: str) -> DownloadDescriptor: ...
    async def set_permission(self, document_id: str, allowed: bool) -> tuple[bool, CorpusDocument]: ...

class DownloadPermissionUpdate(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    download_allowed: bool

class DownloadPermissionResponse(BaseModel):
    document_id: UUID
    download_allowed: bool

class Attachment(BaseModel):
    document_id: UUID
    filename: str
    url: str
    media_type: str
    size: int = Field(ge=0)
```

- [x] Написать API-тест с TestClient(make_app(cfg)), временной мигрированной
  SQLite и файлом, загруженным существующим API. Сценарий:

```python
uploaded = client.post('/api/v1/admin/documents?index=false',
    files={'file': ('spec.pdf', pdf_bytes, 'application/pdf')})
assert uploaded.status_code == 200
row = client.get('/api/v1/admin/documents').json()['corpus'][0]
url = f"/api/v1/documents/{row['document_id']}/download"
assert client.get(url).status_code == 404
permission = url.removesuffix('/download') + '/download-permission'
assert client.patch(permission, json={'download_allowed': True}).status_code == 200
assert client.get(url).content == pdf_bytes
client.patch(permission, json={'download_allowed': False})
assert client.get(url).status_code == 404
```

  Создать pdf_bytes как небольшой валидный тестовый PDF; без реальных AdSmart.
- [x] Запустить `uv run pytest tests/test_downloads.py -q`, подтвердить RED.
- [x] Реализовать resolve: запись по ID → флаг → допустимый относительный путь
  → существующий обычный файл. Не использовать fallback `_document_file`,
  допускающий возврат непроверенного пути после исключения. Запретить абсолютные
  имена, `..`, NUL и компоненты-симлинки. При открытии использовать no-follow
  проход по компонентам относительно открытого docs_dir; передавать файл
  из уже проверенного дескриптора, чтобы повторное открытие по имени не
  обходило проверку симлинка. Закрывать файловые дескрипторы при отказе/отмене.
- [x] В API добавить PATCH и GET/HEAD по ID. Resolve вызывается при каждом
  GET/HEAD; нет записи/разрешения/файла — 404. Список возвращает новые поля,
  загрузка принимает `download_allowed: bool = Query(False)` вместе с index.
  MIME определять по имени, неизвестный тип application/octet-stream.
  Content-Disposition: attachment с корректным filename*; Cache-Control:
  no-store. Читать открытый файл порциями, не read_bytes целиком.
- [x] В первой версии не реализовывать частичные ответы: GET с Range отдаёт
  полный 200, HEAD только заголовки. Не рекламировать Accept-Ranges: bytes.
  BFF всё равно ограничивает такие запросы. Это избежать неоднозначной
  семантики частичных передач и повторного открытия FileResponse.
- [x] Добавить тесты 404 для запретного/несуществующего ID и файла вне реестра,
  traversal, вложенного симлинка, подмены пути; кириллица/пробелы/# в имени;
  отключённая БД; сохранение флага без перестройки индекса; HEAD и Range.
- [x] Логировать сохранение разрешения через существующий logger: event,
  UTC-время, request_id, ID, old/new. Не вводить зависимости HTTP в сервис:
  HTTP-граница получает результат операции и пишет событие после commit.
  Для upload/replace также вернуть внутренние old/new сведения для аудита,
  убрать их из публичного ответа через DTO или явное построение ответа.
- [x] Запустить `uv run pytest tests/test_downloads.py tests/test_documents.py tests/test_architecture.py -q`.
- [x] Коммит `feat: serve permitted document originals`.

## Task 3: BFF-поток, лимиты и журнал передачи

**Files:** создать `frontend/src/lib/server/download-limiter.js`,
`download-proxy.js`, `request-context.js`, маршруты
`frontend/src/routes/api/documents/[documentId]/download/+server.js` и
`download-permission/+server.js`, `frontend/tests/download-proxy.test.js`,
`download-limiter.test.js`; изменить `lib/server/backend.js`,
`routes/api/admin/documents/+server.js`, `frontend/.env.example`.

**Interfaces:**

```javascript
// Ядро limiter независимо от SvelteKit; now возвращает миллисекунды.
createDownloadLimiter({ ratePerMinute, burst, maxConcurrent, maxKeys, now })
// .acquire(ip) -> {ok:true, release()} | {ok:false, retryAfter:number}
// release идемпотентен; новый ключ при полном хранилище не вытесняет активный.

// DI позволяет тестировать реальные Web Streams без поднятого SvelteKit.
proxyDownload({ request, documentId, clientAddress, requestId,
                limiter, upstreamFetch, log }) // -> Promise<Response>
```

- [x] Добавить тесты с управляемым временем:

```javascript
test('cancel releases a concurrency slot', () => {
  const limiter = createDownloadLimiter({
    ratePerMinute: 10, burst: 3, maxConcurrent: 2,
    maxKeys: 100, now: () => 0
  });
  const a = limiter.acquire('192.0.2.1');
  const b = limiter.acquire('192.0.2.1');
  assert.equal(limiter.acquire('192.0.2.1').ok, false);
  a.release(); a.release();
  assert.equal(limiter.acquire('192.0.2.1').ok, true);
  b.release();
});
```

  В реализации отдельно тестировать, что отклонённые по частоте обращения
  не возвращают потраченный токен и не увеличивают число активных передач.
- [x] Запустить `cd frontend && bun test tests/download-limiter.test.js tests/download-proxy.test.js` и подтвердить RED.
- [x] Реализовать token bucket (capacity=3, refill=10/60000 токенов/мс),
  счётчик активных передач, maxKeys=10000; удалять неактивные полностью
  восстановленные записи после 10 минут простоя. При заполнении ограниченного
  хранилища отклонять новый ключ 429, не сбрасывать лимиты существующих.
  Конфигурация: RAGKB_DOWNLOAD_RATE_PER_MINUTE=10,
  RAGKB_DOWNLOAD_BURST=3, RAGKB_DOWNLOAD_MAX_CONCURRENT=2,
  RAGKB_DOWNLOAD_MAX_KEYS=10000. Некорректные значения — ошибка конфигурации.
- [x] Route использует event.getClientAddress(), а не X-Forwarded-For из
  браузера. В прямом запуске не задавать ADDRESS_HEADER. Для Angie deployment
  документировать ADDRESS_HEADER/XFF_DEPTH только при закрытом прямом доступе
  к BFF и перезаписи заголовка доверенным прокси. Не добавлять собственную
  эвристику разбора forwarded-цепочки. Request ID создаётся на BFF, передаётся
  backend, возвращается клиенту; входящий пользовательский ID не доверенный.
- [x] Проверять limiter до upstreamFetch. Использовать AbortController,
  связывая request.signal и cancel потока; освобождать слот на любом пути.
  Порционное чтение по pull сохраняет backpressure. Разрешённые заголовки:
  Content-Type, Content-Disposition, Content-Length для неизменённого тела;
  no-store добавляется также к ошибкам. Не передавать cookies и произвольные
  upstream-заголовки. HEAD освобождает слот сразу после заголовков.

```javascript
const body = new ReadableStream({
  async pull(controller) {
    try {
      const chunk = await reader.read();
      if (chunk.done) { finish('completed'); controller.close(); }
      else { bytes += chunk.value.byteLength; controller.enqueue(chunk.value); }
    } catch (error) { finish('failed'); controller.error(error); }
  },
  async cancel(reason) {
    abort.abort(reason);
    try { await reader.cancel(reason); }
    finally { finish('aborted'); }
  }
});
```

  `finish` определяется в proxyDownload: один вызов освобождает слот, удаляет
  listener request.signal и пишет event с IP/request_id/document_id/bytes.
  Окончание upstream — не доказательство сохранения файла на диске клиента.
- [x] PATCH проксировать JSON с request_id, upload передаёт то же поле аудита.
  Протокол ошибок сохранить: JSON detail, HTTP-статус и Retry-After для 429.
- [x] Тестами проверить 429 без upstream-вызова, независимые IP, восстановление
  токенов, HEAD/Range, сетевой отказ до ответа, отмену до/после headers,
  медленный reader, повторный release, bounded memory, корреляцию аудита.
  Integration-check адреса выполнить реальным SvelteKit запросом с подложным
  X-Forwarded-For: он не меняет ключ в direct-режиме.
- [x] Запустить `bun test && bun run check`. Коммит `feat: limit and audit streamed downloads through BFF`.

## Task 4: Подготовить кандидатов и контракт событий агента

**Files:** создать `backend/ragkb/services/download_candidates.py`,
`core/answer_events.py`, `tests/test_download_candidates.py`; изменить
`core/ports.py`, `services/downloads.py`, `api/schemas/ask.py`.

**Interfaces:**

```python
# core/answer_events.py, stdlib dataclasses/typing, без импортов верхних слоёв
class ToolCandidate(TypedDict):
    document_id: str
    filename: str
    download_allowed: bool

ToolResult = dict[str, Any]  # success поля Attachment либо error='not_available'
DownloadResolver = Callable[[str], Awaitable[ToolResult]]

@dataclass(frozen=True)
class AnswerEvent:
    kind: Literal['token', 'attachment', 'warning']
    value: str | dict[str, Any]

# services/download_candidates.py
async def prepare_candidates(question, hits, registry, docs_dir) -> list[ToolCandidate]: ...
def match_names(question: str, names: list[str]) -> list[str]: ...
```

- [ ] Написать тесты нормализованного сопоставления:

```python
def test_html5_does_not_silently_select_mobile():
    names = ['AdSmart HTML5.pdf', 'AdSmart Mobile HTML5.pdf']
    assert match_names('Пришли AdSmart Mobile HTML5', names) == [names[1]]
    assert set(match_names('Пришли требования HTML5', names)) == set(names)
```

- [ ] Запустить `uv run pytest tests/test_download_candidates.py -q`, подтвердить RED.
- [ ] Реализовать сравнение casefold/NFKC, без расширения, пунктуация как
  разделители; точное полное название получает приоритет, иначе совпадение
  содержательных токенов (служебные «пришли», «требования», «к» исключаются).
  Не превращать выбор кандидатов в автоматическое разрешение инструмента;
  неоднозначность видна модели. До 20 кандидатов; если превышено, попросить
  конкретизировать и не отдавать случайную усечённую подборку инструменту.
- [ ] Объединить найденные по имени разрешённые записи с привязанными к hits
  документами, дедуплицировать по ID. Привязка проверяет принадлежность source
  каталогу docs_dir и реестру, не использует один basename для чужого пути.
  Закрытые hits остаются для цитирования с false; кандидаты не содержат path.
- [ ] Создать request-scoped callback, принимающий только разрешённые ID
  этого набора. Внутри повторно вызвать DownloadsService.resolve; строить URL
  из ID на сервере; отказ вернуть как error=not_available. Нет БД → пустые
  кандидаты и отказ инструмента, без отказа обычного ответа.
- [ ] Описать Pydantic TokenEvent/DoneEvent и Attachment на границе API,
  не импортируя API DTO в core. DoneEvent сохраняет существующие поля и
  добавляет attachments с default_factory=list.
- [ ] Проверить совпадения Premium, одинаковые названия фрагментов, запрещённый
  ID, отсутствие БД, PDF вне top-k при источнике DOCX и отзыв флага после
  подготовки кандидатов. Запустить tests/test_download_candidates.py и
  tests/test_architecture.py. Коммит `feat: resolve registered download candidates for answers`.

## Task 5: Настоящий цикл инструментов и NDJSON

**Files:** создать `backend/ragkb/core/tool_answers.py`,
`tests/test_tool_answers.py`; изменить `core/pipeline.py`, `core/prompts.py`,
`core/ports.py`, `services/ask.py`, `api/routes/ask.py`,
`api/deps/services.py`, `tests/helpers.py`, `tests/test_stream.py`, `tests/test_ask.py`.

**Interfaces:** добавить к AnswerEngine, оставив search/cited_sources и
существующий синхронный путь оценки работоспособными:

```python
def stream_tool_answer(
    self, question: str, *, hits: list[Hit], model: str,
    candidates: list[ToolCandidate], resolve_download: DownloadResolver,
) -> AsyncIterator[AnswerEvent]: ...

# AskService: подготовка вызывается до открытия StreamingResponse.
async def stream(self, question: str, *, model=None, top_k=None, expand=False
) -> AsyncIterator[str]: ...
# route: stream = await svc.stream(**req.model_dump())
```

- [ ] Расширить ScriptedChatModel поддержкой bind_tools и скриптом AIMessage/
  AIMessageChunk с настоящими tool_calls; сохранить существующие текстовые
  responses. Добавить детерминированный тест:

```python
request_tool = AIMessage(content='', tool_calls=[{
    'name': 'get_download_link', 'args': {'document_id': doc_id}, 'id': 'call-1'
}])
final_text = AIMessage(content='Требования приложены. [1]')
# Скрипт возвращает request_tool, затем final_text.
# Проверить: callback вызван один раз; второй вызов модели содержит ToolMessage
# с tool_call_id='call-1'; done.attachments[0].document_id == doc_id.
```

- [ ] Запустить `uv run pytest tests/test_tool_answers.py -q`, подтвердить RED.
- [ ] В core связать модель с одним инструментом через bind_tools. Обрабатывать
  astream сообщений, складывать AIMessageChunk до получения полных аргументов;
  пользовательский текст передавать токенами, JSON аргументов не выводить.
  После окончания раунда добавить AIMessage и соответствующие ToolMessage,
  выполнить callback асинхронно. Tool schema: object с обязательным UUID
  document_id и additionalProperties=false. Не использовать StrOutputParser
  между моделью и обработчиком tool_calls.
- [ ] Предел: до 3 раундов с инструментами и 8 вызовов суммарно; затем один
  финальный проход без разрешённых инструментов. Превышение/неизвестный tool/
  невалидный JSON/ID — warning и контролируемый ToolMessage. Успешный ID
  повторно не исполнять, возвращать сохранённый результат; attachment один.
  Не перехватывать отмену клиента как обычную ошибку и не продолжать генерацию.
- [ ] До открытия потока сохранить существующие 400/503 проверки. Синхронный
  retrieval выполнять через asyncio.to_thread; реестр/callback await.
  Не выполнять asyncio.run и не блокировать loop синхронным итератором LLM.
- [ ] AskService сериализует AnswerEvent в token и итоговый done; вложения
  собирает только из событий attachment, цитаты только из текста/hits.
  Ошибка генерации сохраняет полученный текст/вложения и даёт warnings;
  truncated=true после начавшегося ответа. Не создавать карточки из слов модели.
- [ ] Промпт определяет политику прямой просьбы/подготовки материалов/
  неоднозначности; запрещает исполнять инструкции из источников. При уточнении
  предлагает полную следующую формулировку без обещания памяти диалога.
- [ ] Исправить OpenAPI /ask на application/x-ndjson; схемы token/done
  документируют каждую строку как union, а не один JSON-массив. Проверить
  app.openapi() без запуска реального приложения и внешних моделей.
- [ ] Проверить частичные tool-call chunks, несколько вызовов в одном ответе,
  повторный ID, отказ после отзыва, неизвестный инструмент, лимиты, обрыв
  до/после вложения, отсутствие вызовов, отсутствие БД и два независимых ask.
  Запустить `uv run pytest tests/test_tool_answers.py tests/test_stream.py tests/test_ask.py tests/test_pipeline.py tests/test_architecture.py -q`.
- [ ] Коммит `feat: stream answers with verified download tool calls`.

## Task 6: Переключатели и карточки во фронтенде

**Files:** создать `frontend/src/lib/components/chat/Attachments.svelte`,
`frontend/src/lib/download.js`, `frontend/tests/download.test.js`;
изменить `routes/admin/documents/+page.svelte`, `lib/chat.svelte.js`,
`lib/components/chat/Message.svelte`, `frontend/tests/answer-stream.test.js`.

**Interfaces:**

```javascript
// Message.attachments: Array<{document_id, filename, url, media_type, size}>
// attachments при старом done отсутствует и трактуется как [].
// download.js:
downloadAttachment(attachment, { fetchImpl = fetch, saveBlob }) // Promise<void>
// saveBlob(blob, filename) вызывается только после response.ok.
```

- [ ] Написать тест ошибок скачивания и совместимости потока:

```javascript
test('revoked file does not save an error body', async () => {
  let saved = false;
  await assert.rejects(downloadAttachment(attachment, {
    fetchImpl: async () => new Response('{"detail":"Недоступен"}', {status: 404}),
    saveBlob: () => { saved = true; }
  }), /недоступен/i);
  assert.equal(saved, false);
});
```

  attachment в тесте — фиксированный UUID, filename=spec.pdf,
  url=/api/documents/<UUID>/download, media_type=application/pdf, size=10.
- [ ] Запустить `bun test tests/download.test.js tests/answer-stream.test.js`,
  подтвердить RED новых сценариев.
- [ ] В загрузке добавить флаг false для новой пачки; snapshot значения хранить
  в QueueItem, чтобы изменение переключателя не меняло уже запущенную очередь.
  Передавать через URLSearchParams вместе с index=false. При замене явно
  показывать итоговый флаг. В таблице переключатель сохраняется PATCH по ID,
  блокируется на время запроса; при ошибке восстанавливает прежнее состояние.
- [ ] Обновить тип Message и обработку done: attachments ?? []. Показывать
  Attachments даже при пустом тексте ответа. Карточки: имя, размер, кнопка,
  локальная ошибка. Validate URL как same-origin путь /api/documents/<id>/download
  совпадающий с document_id; не скачивать произвольный URL из неизвестных данных.
- [ ] По клику fetch файла; 404 — «Файл больше недоступен», 429 — предложение
  повторить с Retry-After, остальные отказы — понятная ошибка. Успешное тело
  сохранить через Blob/object URL, затем revokeObjectURL. BFF остаётся потоковым;
  браузер собирает один файл в Blob (загрузка сейчас ограничена 20 МБ).
  Повторные клики блокируются до завершения; не делать HEAD перед каждым GET.
- [ ] Проверить тестами 200/404/429, вредоносный URL, старый done, вложение без
  текста и сохранение текста после ошибки скачивания. Проверить вручную в
  браузере загрузку, смену флага, замену, две карточки, копирование, источники,
  очистку чата и узкий экран; клавиатурные подписи кнопок и переключателей.
- [ ] Запустить `bun test && bun run check && bun run build`.
- [ ] Коммит `feat: manage download permissions and show chat attachments`.

## Task 7: Сквозная проверка, документация и передача

**Files:** изменить `README.md`, `frontend/README.md`, `AGENTS.md`,
`backend/tests/test_logging.py`; дополнить тесты предыдущих задач по результатам.

- [ ] Обновить инструкции: 0001 → новая head через alembic upgrade head;
  прежние удалённые исторические ревизии сначала stamp --purge 0001, затем
  upgrade head. Не stamp сразу 0002, иначе новые столбцы не будут созданы.
  Описать выключенный default, смену флага без reindex, замену/удаление,
  требование tool calling и независимость вопросов.
- [ ] Документировать limiter одного процесса, общий NAT, доверенные прокси,
  отсутствие квоты байтов; включить настройки из задачи 3 в frontend/.env.example.
  Указать, что скачанные файлы нельзя отозвать и аудит не устанавливает личность.
- [ ] Дописать log-тест с caplog: успешное изменение имеет old/new и request_id,
  неуспешное не выдаётся за сохранённое; выдача ссылки не создаёт download_completed.
  Проверить, что текущие ротационные логи работают без новой таблицы или sink.
- [ ] Полная проверка:

```bash
cd backend && uv run pytest
cd frontend && bun test && bun run check && bun run build
```

  Команды запускать из соответствующего каталога, не выполнять второй cd
  относительно backend. Проверить git diff --check. Не повторять полный набор
  без новых изменений/сбоев.
- [ ] На изолированной тестовой Postgres проверить upgrade с 0001 и сохранение
  документов/посторонней таблицы. Если Docker/Postgres недоступен, записать
  ограничение проверки явно, не выдавать SQLite за проверку Postgres.
- [ ] Сквозной сценарий через BFF с тестовыми файлами: закрытый источник знаний
  + разрешённый PDF; tool → done → карточка → байты; отзыв → 404; лимит → 429;
  prompt без tool → обычный ответ. Воспроизводить детерминированно, затем
  отдельно с настроенной моделью при её доступности. Не менять флаги реальных
  AdSmart или DOCX без отдельной команды пользователя.
- [ ] Провести финальное ревью diff относительно spec, включая отсутствие
  файлов корпуса/секретов в изменениях. Выполнить verification-before-completion
  и finishing-a-development-branch при завершении реализации.
- [ ] Коммит документации/финальных поправок `docs: document download tools and operational limits`.

## Покрытие спецификации и решения плана

| Требование | Задачи |
|---|---|
| Реестр, UUID, default, миграция и замена | 1 |
| Серверная проверка, пути, GET/HEAD, отзыв | 2 |
| BFF, rate limiting, доверенный IP, аудит передачи | 3 |
| Кандидаты вне top-k, реестр, схемы | 4 |
| Tool calling, асинхронность, ошибки, лимиты, NDJSON | 5 |
| Загрузка/переключатели/карточки/ошибки | 6 |
| Аудит изменений, документация и сквозная проверка | 2, 7 |

Уточнения исполнения: Range обслуживается полным 200, а не частичной выдачей;
финальный проход модели после лимита tools запрещает новые инструменты;
аудит добавляется в существующие логи; интерфейс скачивания буферизует в
браузере только один файл до текущего лимита загрузки, серверный тракт потоковый.

## Execution Handoff

План подготовлен для проверки. Рекомендация — последовательное выполнение
в текущей задаче: шаги сильно связаны контрактами реестра, событий и callback.
Вариант с отдельными исполнителями и ревью каждого шага возможен по выбору
пользователя. До проверки плана и выбора способа реализацию не начинать.

## Ход выполнения

### Task 1 — выполнено

Ветка `feat/document-download-tools`; спецификация и план закоммичены отдельно
(`docs: add document download tools spec and plan`). Навыки Superpowers в этой
сессии недоступны, поэтому процесс выполнен вручную в том же порядке:
тест → подтверждение ожидаемого падения → реализация → проверки → ревью diff.

Изменённые файлы этапа: `backend/migrations/versions/0002_document_downloads.py`
(новый), `backend/ragkb/domain/entities.py`, `backend/ragkb/domain/ports.py`,
`backend/ragkb/db/models.py`, `backend/ragkb/db/repos/corpus_documents.py`,
`backend/ragkb/core/database.py`, `backend/ragkb/services/documents.py`,
`backend/tests/helpers.py`, `backend/tests/test_guard.py`,
`backend/tests/test_download_registry.py` (новый).

Фактические результаты проверок:

- RED: `cd backend && uv run pytest tests/test_download_registry.py -q` —
  7 падений, все на `AttributeError: 'CorpusDocument' object has no attribute
  'document_id'` и `sqlite3.OperationalError: no such column: document_id`,
  то есть из-за отсутствующего контракта, а не настройки окружения.
- GREEN: те же 8 тестов проходят.
- `uv run pytest tests/test_download_registry.py tests/test_documents.py
  tests/test_architecture.py -q` — 54 passed
  (8 + 31 + 15).
- Полный backend-набор: `cd backend && uv run pytest` — 219 passed,
  1 deselected (`integration`).
- `uv run ruff check ragkb migrations tests` — 11 замечаний, все
  существовавшие до этапа (было 12; строка в `tests/test_guard.py` укорочена
  при правке). Новых замечаний этап не добавил.

Ограничения проверок и решения по ходу:

- Миграция проверена только на временной SQLite. Postgres не проверена:
  `docker` CLI установлен, но демон недоступен (`/var/run/docker.sock`
  отсутствует). Локальный порт 5432 слушает, но это может быть рабочая база
  заказчика, а её учётные данные — секрет, поэтому он не использовался.
  Проверка на изолированной Postgres остаётся за Task 7.
- `backend/tests/test_guard.py` пришлось поправить: тест вставлял запись
  реестра сырым SQL без идентификатора, а с ревизии 0002 столбец обязателен.
  Строка теперь содержит UUID; смысл теста (повторный upgrade не теряет
  принятые документы) сохранён.
- `document_id` в модели и миграции — `String(36)`: каноническая запись UUID
  как единый контракт схемы.
- Список документов (`GET /api/v1/admin/documents`) и HTTP-параметр загрузки
  `download_allowed` намеренно не менялись — это Task 2 вместе с выдачей
  оригинала.
- Докстринг `0001_corpus_documents.py` («Единственная миграция проекта»)
  устарел: переписывать 0001 план запрещает, поэтому фактическое описание
  цепочки живёт в 0002, а README и AGENTS.md актуализируются в Task 7.

### Task 1 — исправление по ревью: сериализация изменения разрешения

Замечание координации: `PostgresCorpusDocuments.set_download_allowed` полагался
на `SELECT ... FOR UPDATE`, который SQLite игнорирует. Гонка воспроизведена
независимо до правки: два одновременных вызова `set_download_allowed(id, True)`
вернули `[False, False]` — оба сообщили одно и то же прежнее значение, хотя
одну замену выполнил второй запрос. Это ломает обещанные old/new для журнала.

Что изменено в `backend/ragkb/db/repos/corpus_documents.py`:

- добавлен `_lock_document_write`: на SQLite операция открывается
  `BEGIN IMMEDIATE` до чтения строки, поэтому чтение прежнего значения и запись
  нового — одна сериализованная операция;
- для Postgres сохранён `FOR UPDATE`: блокировку строки держит сам запрос;
- в докстрингах зафиксировано, почему одного `FOR UPDATE` мало и что при
  невзятии блокировки за busy timeout операция падает ошибкой базы, а не отдаёт
  неверное прежнее значение.

Решения по тестам (все в `backend/tests/test_download_registry.py`):

- `test_simultaneous_permission_changes_report_distinct_previous_values` —
  детерминированный конкурентный детектор: обе операции стартуют вместе, а
  первое чтение ждёт второго с ограничением 0.5 с. Ограничение обязательно:
  под корректной блокировкой второе чтение до конца изменения невозможно, и
  ожидание истекает — это не взаимная блокировка. Без блокировки вторая
  операция успевает прочитать `false` до первой записи. Барьер после чтения
  без ограничения по времени не используется именно из-за deadlock.
- `test_sequential_permission_changes_report_previous_values` — прежнее
  значение совпадает с реально заменённым (False→True, True→False, False→False)
  и отсутствующий документ даёт `None`.
- `test_failed_permission_change_keeps_value_and_releases_lock` — отказ записи
  откатывает изменение и не оставляет блокировку: следующее изменение проходит.

Доказательство, что тест обнаруживает старое поведение: базовый коммит
`34cc931` выложен отдельным временным checkout
(`git worktree add --detach /tmp/ragkb-baseline 34cc931`), в него скопирован
новый файл тестов, импорт проверен (`ragkb` из
`/private/tmp/ragkb-baseline/backend/ragkb/__init__.py`). Конкурентный тест
упал там 5 раз из 5 (`[False, False]`), исправленная версия проходит 6 раз из 6
(`[False, True]`). Временный worktree удалён; `git stash` не использовался.

Фактические результаты после исправления:

- `uv run pytest tests/test_download_registry.py -q` — 11 passed.
- Полный backend-набор — 222 passed, 1 deselected (`integration`).
- `uv run ruff check ragkb migrations tests` — те же 11 замечаний, что и до
  правки: новых нет.

Ограничения исправления:

- Postgres по-прежнему не проверена запуском (docker-демон недоступен);
  ветка `FOR UPDATE` осталась без изменений и ждёт проверки Task 7.
- SQLite сериализует писателей и без этой правки, поэтому `BEGIN IMMEDIATE` не
  снижает реальную параллельность дополнительно — он лишь включает чтение в ту
  же блокировку. Если блокировку не удаётся взять за busy timeout драйвера
  (5 с), изменение падает ошибкой базы; преобразование в понятный HTTP-отказ
  (409/503 с повтором) — вопрос Task 2, здесь намеренно не расширялся.
- `MemoryRegistry` в тестах блокировок не имеет: его операции не содержат
  `await` внутри изменения, поэтому в одном цикле событий они атомарны.

### Task 2 — выполнено

Новые единицы ответственности: `services/downloads.py` (проверка реестра,
разрешения и пути, открытие файла без симлинков), `api/schemas/downloads.py`
(DTO разрешения и вложения), `api/routes/downloads.py` (PATCH разрешения,
GET/HEAD оригинала), `api/audit.py` (запись изменений разрешения в существующий
журнал и `request_id`), `tests/test_downloads.py` (20 тестов). Изменены
`api/router.py`, `api/deps/services.py`, `api/routes/documents.py`,
`api/errors.py`, `services/documents.py`, `db/repos/corpus_documents.py`,
`domain/entities.py`, `domain/ports.py`, `tests/helpers.py`,
`tests/test_documents.py`, `tests/test_download_registry.py`.

Отличия от буквы плана и их причины:

- `DownloadDescriptor` получил поле `handle`: файл отдаётся из уже проверенного
  дескриптора, а не повторным открытием по имени — иначе проверка симлинков
  между проверкой и открытием ничего не значит. Путь по-прежнему не
  сериализуется.
- `DocumentRegistry.record` теперь возвращает `RecordOutcome` (признак создания,
  прежнее разрешение, запись). Это требование ревью: аудит загрузки и замены
  обязан брать old/new из самой записи, а не из чтения до неё. `record` на
  SQLite тоже берёт блокировку записи до чтения — иначе два одновременных
  запроса вернули бы одно и то же прежнее значение.
- `DocumentsService.upload` возвращает `UploadResult` (публичный `payload` и
  сведения для журнала): HTTP-граница пишет событие сама, а наружу отдаёт
  только payload.
- Добавлен `api/audit.py` — план не перечислял отдельный модуль, но одна общая
  точка записи события лучше двух одинаковых строк в маршрутах. Заголовок метки
  запроса — `X-Request-Id`; его будет присылать BFF в Task 3.
- `api/errors.py` получил публичный `status_for(exc)`: отказы выдачи собираются
  на месте, чтобы добавить `Cache-Control: no-store`, и статус берётся из той же
  таблицы, что и в общем хендлере.
- `uv`-запуск: `uv run pytest tests/test_downloads.py -q` сначала дал 17 падений
  (нет маршрутов, нет `document_id` в списке, нет параметра загрузки) — RED по
  делу, затем GREEN.

Фактические результаты:

- `uv run pytest tests/test_downloads.py -q` — 20 passed.
- `uv run pytest tests/test_downloads.py tests/test_download_registry.py
  tests/test_documents.py tests/test_architecture.py -q` — 77 passed.
- Полный backend-набор — 242 passed, 1 deselected (`integration`).
- `uv run ruff check ragkb migrations tests` — 11 замечаний, все прежние;
  новых нет.

Ограничения и открытые вопросы:

- Postgres не проверена запуском (docker-демон недоступен). Ветка `FOR UPDATE`
  в `set_download_allowed` и `record` не менялась, миграция на Postgres ждёт
  Task 7.
- Частичные ответы (Range) не реализованы: GET с Range отдаёт полный 200,
  `Accept-Ranges` не рекламируется. Это решение плана, а не недосмотр.
- Скачивание пока не ограничивается по частоте и не журналируется на границе:
  это Task 3 (BFF). Backend пишет только отказ выдачи и изменение разрешения.
- `document_id` в маршрутах принимается строкой, некорректный UUID даёт 404, а
  не 422: ответ не должен подтверждать, что идентификатор «почти» верный.

### Task 2 — исправление по второму кругу ревью

Замечания координации: открытие FIFO блокирует цикл событий; `record` без
`FOR UPDATE` не атомарен на Postgres; порядка публикации мало — конкурентный
GET может прочитать прежнюю разрешённую запись и открыть уже новые байты;
журнал не должен скрывать чужие изменения между «снять» и «выдать».

Что изменено:

- `services/downloads.py::_open_document` открывает конечный компонент с
  `O_NONBLOCK`: FIFO больше не ждёт писателя, проверка `S_ISREG` осталась и
  отсекает всё, кроме обычных файлов.
- `db/repos/corpus_documents.py::record` читает существующую строку с
  `with_for_update=True` (на SQLite, как и раньше, предварительный
  `BEGIN IMMEDIATE`). Заодно исправлена аннотация возврата: `RecordOutcome`,
  а не `None`.
- `services/documents.py::upload` публикует замену в два шага: содержимое
  пишется во временный файл рядом, затем **одна** атомарная запись реестра с
  запрошенным разрешением, затем `os.replace`. Промежуточного «снять, потом
  выдать» больше нет: пара old/new в журнале описывает ровно то, что сделала
  одна запись, а отказ записи не публикует ничего и не трогает прежнее
  разрешение. Режим доступа прежнего файла сохраняется.
- `services/downloads.py::resolve` сверяет SHA-256 **уже открытого**
  дескриптора с хэшем из прочитанной записи: чтение порциями через
  `asyncio.to_thread`, затем `seek(0)`; несовпадение — 404 (fail closed).
  `os.replace` не меняет байты у открытого inode, поэтому совпадение хэша
  означает, что выдаются именно те байты, вместе с которыми прочитано
  разрешение. Запись без хэша не выдаётся вовсе — это явная политика, а не
  обход проверки; событие попадает в журнал предупреждением.

Доказательства, что тесты ловят дефекты (временный checkout `3ae446c`, затем
симуляция отсутствующей блокировки в `record`; рабочее дерево не менялось):

- FIFO, порядок публикации, отказ записи, запись без хэша и конкурентная
  подмена при GET — 5 тестов падают на прежнем коде
  (`test_get_does_not_serve_content_that_replaced_the_record` получал 200 с
  новым закрытым содержимым).
- `test_simultaneous_replacement_and_permission_change_agree` с исходным
  разрешением `true` и двумя снятиями: при удалении блокировки в `record`
  оба изменения сообщают `previous=true` (ожидается ровно одно `true`), на
  базовом коде тест проходит — значит, он чувствителен именно к блокировке.

Фактические результаты:

- `uv run pytest tests/test_downloads.py -q` — 26 passed.
- Целевые четыре файла — 84 passed; полный backend-набор — 249 passed,
  1 deselected.
- `uv run ruff check ragkb migrations tests` — те же 11 прежних замечаний.

Ограничения этого исправления:

- Postgres-ветка `FOR UPDATE` по-прежнему не проверена запуском: docker-демон
  недоступен. Проверка остаётся за Task 7.
- HEAD тоже считает хэш файла, то есть читает его целиком: это цена того, что
  заголовки HEAD и решение GET не расходятся. Ограничение частоты и объёма —
  задача BFF (Task 3).
- Два одновременных upload одного имени могут оставить в реестре одну версию,
  а на диске другую: такая пара не проходит сверку, и выдача закрывается
  отказом до повторной загрузки. Это осознанный fail closed, а не выдача
  «чего получится».

### Task 2 — дополнение к ревью: сценарий замены и уточнения

Замечание координации: сценарий замены с принудительным отказом `record`
воспроизведён независимо — после ошибки `DownloadsService.resolve(old_id)`
возвращал новый закрытый файл. Это не гонка, а прямое следствие порядка
«сначала файл, потом запись».

Проверено на двух состояниях одним и тем же скриптом (временный checkout
`3ae446c`, рабочее дерево не менялось):

- на `3ae446c` сценарий воспроизводится дословно: файл на диске
  `b"%PDF new private\n"`, выдача возвращает его же;
- на `b48fc26` (текущее состояние) тот же скрипт даёт прежний файл
  `b"%PDF old public\n"`, лишних файлов в каталоге нет, строка реестра
  сохраняет прежний хэш и разрешение.

Добавлен сервисный регрессионный тест
`test_failed_replacement_keeps_old_bytes_under_permission`: он повторяет этот
сценарий на уровне сервиса (принудительный `Conflict` в `record`, затем
`resolve` и чтение дескриптора) и на прежнем коде падает с сообщением «выдача
не должна отдавать неопубликованную замену». Прежняя проверка была только на
уровне API, теперь контракт закреплён и там, где дефект наблюдался.

Уточнения по замечаниям:

- Аудит передачи (начало, завершение, обрыв, IP) остаётся на внешнем BFF в
  Task 3: дублировать полный потоковый аудит на backend не требуется. Backend
  пишет изменение разрешения и отказ выдачи — этого достаточно для связывания
  записей по `request_id`.
- `test_closed_document_stays_searchable_and_needs_no_reindex` (прежнее имя —
  `test_permission_change_needs_no_reindex_and_keeps_search`) теперь ищет
  документ **при выключенном** разрешении: заявленный сценарий — закрытый
  документ остаётся доступен поиску и цитатам, — а прежняя версия проверяла
  поиск уже после включения флага и подтверждала не то.

Фактические результаты: `tests/test_downloads.py` — 27 passed; полный
backend-набор — 250 passed, 1 deselected; ruff — те же 11 прежних замечаний.
### Task 2 — третье замечание ревью: аудит при отказе индексации

Замечание: изменение `download_allowed`, уже сохранённое записью реестра,
терялось в журнале, если следующая за ним индексация падала. Причина — маршрут
писал событие только после успешного завершения `svc.upload`, а 503 приходит
уже после сохранения.

Что изменено:

- `services/documents.py::upload` получил необязательный колбэк
  `on_permission_change: Callable[[PermissionChange], None]`, который
  вызывается сразу после сохранения записи реестра — до публикации файла и до
  индексации. `PermissionChange` (document_id, action, previous, current) —
  плоские типы, HTTP-зависимостей в сервисе не появилось.
- `api/routes/documents.py` передаёт колбэк, который пишет событие в журнал
  вместе с `request_id`; прежняя запись «после успешного upload» убрана.
  Отказ самой записи в реестр колбэк не вызывает, поэтому неудавшееся
  изменение успешным не выглядит.
- `on_permission_change` по умолчанию `None`: остальные вызовы `upload`
  (тесты, сервисы) не обязаны знать про журнал.

Проверка детекции: временный checkout `8cdbea6` — регрессионный тест
`test_permission_change_is_audited_when_indexing_fails` падает там ровно на
заявленном сценарии: POST возвращает 503, файл скачивается, а в журнале есть
только строка первой загрузки (`old=false new=false`), события `false→true`
нет. На текущем состоянии событие ровно одно и содержит `action=replace`,
`request_id=req-index` и идентификатор документа.

Фактические результаты: `tests/test_downloads.py` — 28 passed; полный
backend-набор — 251 passed, 1 deselected; ruff — те же 11 прежних замечаний.
### Task 3 — выполнено

Новые файлы: `frontend/src/lib/server/download-limiter.js`,
`download-proxy.js`, `request-context.js`,
`frontend/src/routes/api/documents/[documentId]/download/+server.js`,
`download-permission/+server.js`, `frontend/tests/download-limiter.test.js`,
`download-proxy.test.js`. Изменены `lib/server/backend.js` (адрес backend
отдельной функцией), маршрут загрузки документов (метка запроса),
`frontend/.env.example`, а также `backend/ragkb/api/routes/downloads.py`: строка
отказа выдачи теперь несёт `request_id` от BFF — без него события frontend и
backend не сопоставить.

Решения по ходу:

- Ограничитель — чистый модуль без SvelteKit: время, значения и адрес приходят
  снаружи, поэтому лимиты проверяются без ожидания реальных секунд. Счётчики
  живут в процессе frontend; при нескольких репликах общий лимит даёт только
  внешний прокси — это записано в `.env.example`.
- Порядок проверок в `acquire`: частота → параллелизм → списание токена и слота.
  Отклонённый запрос не тратит ни токен, ни слот передачи (проверено тестом), а
  новый ключ при заполненном хранилище не вытесняет существующие.
- Адрес берётся только у соединения (`event.getClientAddress()`); заголовки
  браузера не читаются вовсе. Тест с подложенным `X-Forwarded-For` подтверждает,
  что ключ лимита не меняется.
- Тело не буферизуется: чтение порциями по требованию потребителя, «вперёд не
  больше одной порции» проверено счётчиком чтений upstream. Слот освобождается
  ровно один раз — при завершении, отмене по сигналу запроса, отмене
  потребителем и ошибке.
- Клиенту уходят только `content-type`, `content-disposition`, `content-length`,
  добавленные `cache-control: no-store` и `x-request-id`; cookies и прочие
  заголовки backend не пробрасываются, а upstream получает только метку запроса.
- Журнал BFF различает `refused` (лимит или отказ backend), `started`,
  `completed`, `aborted`, `failed` и несёт IP, request_id, document_id, байты и
  длительность. Полный потоковый аудит остаётся на BFF: backend пишет изменение
  разрешения и отказ выдачи, как договорено.

Фактические результаты:

- RED: новые тесты сначала падали на отсутствующих модулях.
- `cd frontend && bun test` — 22 passed (8 ограничитель, 12 прокси, 2 потока
  ответа).
- `bun run check` — 0 ошибок, 0 предупреждений; `bun run build` собирается.
- Полный backend-набор — 251 passed, 1 deselected; ruff — те же 11 прежних
  замечаний.
- Живая проверка на dev-сервере SvelteKit: пять запросов с разными подложенными
  `X-Forwarded-For` дали три прохода и два `429` с `Retry-After`, в журнале у
  всех `ip=127.0.0.1` — ключ берётся из соединения.
- Сквозная проверка через BFF с настоящим backend на временном корпусе: `GET`
  разрешённого документа — 200 и те же байты (23 байта, `content-type`,
  `content-disposition` с `filename*`, `content-length`, `no-store`,
  `x-request-id`), `HEAD` — заголовки без тела, закрытый документ — 404, журнал
  BFF дал `started` → `completed bytes=23`, а строка отказа backend содержит тот
  же `request_id`, что и строка BFF.

Ограничения:

- Лимит — одного процесса frontend: несколько реплик дают независимые счётчики,
  и выдавать их за глобальную защиту нельзя.
- Частота и параллелизм не задают потолок трафика: жёсткий бюджет байтов
  требует квоты или ограничения скорости на внешнем прокси.
- `ADDRESS_HEADER`/`XFF_DEPTH` не задаются в прямом запуске: их включает только
  закрытый прямой доступ к BFF и доверенный прокси, иначе адрес подставляется.
- Интеграционная проверка адреса и сквозной сценарий выполнены вручную
  (dev-сервер и uvicorn на временном корпусе); автоматическими тестами они не
  покрыты — поднимать SvelteKit внутри `bun test` дороже, чем польза.
### Task 3 — исправление по ревью

Замечания координации к `51e9f63`:

- [P1] слот оставался занятым, если запрос отменяли, когда порция уже лежала в
  буфере выходного потока: освобождение зависело от следующего `pull` или
  `cancel`, которых при нечитающем клиенте уже не было. `onAbort` теперь сам
  завершает передачу (`finish('aborted', …)`) — освобождение слота, удаление
  listener и запись `aborted` происходят сразу, `finish` идемпотентен, upstream
  по-прежнему останавливается. Счётчик байт поднят к состоянию передачи, чтобы
  обрыв и завершение видели одно и то же значение.
- [P2] обход в `prune` начинался с начала `Map`: если первые 64 записи были
  заняты, просроченные дальше не проверялись никогда. Обход теперь продолжается
  с прошлого места (хранимый итератор, сброс после полного круга), работа на
  запрос остаётся ограниченной 64 записями, активные передачи не вытесняются, а
  лимиты существующих адресов не сбрасываются.

Регрессионные тесты и доказательство детекции (временный checkout `51e9f63`):

- `aborting with an unread buffered chunk frees the slot` — на прежнем коде
  падает с «слот остался занятым», потому что ни `reader.read()`, ни `cancel()`
  в тесте не вызываются.
- `prune resumes its sweep instead of restarting it` (64 занятых адреса,
  `maxKeys=65`, простой больше десяти минут) — на прежнем коде падает с
  «просроченная запись не освободила место для нового адреса».

Фактические результаты: `bun test` — 24 passed (13 прокси, 9 ограничитель,
2 потока ответа); `bun run check` — 0 ошибок, 0 предупреждений; `bun run build`
собирается; полный backend-набор — 251 passed, 1 deselected.
