# План реализации: переключение моделей на ходу

> **Для агентов:** ОБЯЗАТЕЛЬНЫЙ ПОДНАВЫК — используйте
> superpowers:subagent-driven-development (рекомендуется) либо
> superpowers:executing-plans. Шаги размечены чекбоксами (`- [ ]`).

**Цель:** сотрудник выбирает модель и число фрагментов прямо в интерфейсе,
не перезапуская сервис; видно, каким выбором получен каждый ответ.

**Архитектура:** имя модели приходит параметром запроса и проверяется по списку
разрешённых из конфигурации — свободный ввод заставил бы Ollama скачивать
произвольные модели. Пайплайн собирает объект LLM под конкретный запрос
из копии настроек; сервер состояния не хранит, выбор помнит браузер.

**Технологии:** Python 3.10+, FastAPI, SQLite, ванильный JavaScript.
Новых зависимостей не добавляется.

**Спека:** `docs/superpowers/specs/2026-08-20-model-switching-design.md`

**Предшествующая работа:** всё в `main`. Есть `ragkb/auth.py`,
`ragkb/history.py` со схемой версии 2 и лестницей миграций, `ragkb/ui.py`
с чатом, `/ask` и `/ask/stream` с NDJSON.

## Общие ограничения

- **Новых зависимостей в `pyproject.toml` не добавлять.**
- **Имя модели проверяется по списку `llm.available`.** Имя вне списка —
  отказ 400. Свободный ввод недопустим: незнакомое имя заставит Ollama
  скачивать модель, это десятки минут задержки и заполнение диска по запросу
  извне.
- **Пустой `available` сохраняет нынешнее поведение:** переключения нет,
  работает `llm.model`. Обратная совместимость обязательна.
- **Рассуждающие модели не поддерживаются.** Признака в конфигурации, события
  `thinking` и отдельного `max_tokens` на модель не будет — код остаётся
  безразличным к тому, какая модель указана.
- **Эмбеддер не переключается.** `RAGPipeline._restore_embedder` отказывается
  работать при расхождении с манифестом; трогать это нельзя.
- **Проверка имени модели выполняется до начала потока**, чтобы отказ пришёл
  кодом ответа, а не событием: после первого байта статус уже отправлен.
- **Пустой ответ модели даёт предупреждение**, а не пустое сообщение.
- **Тесты запускаются без pytest:** `python tests/test_models.py`, раннер
  по `globals()`, функции без обязательных аргументов. Образцы —
  `tests/test_stream.py`, `tests/test_history.py`.
- **Язык кода, комментариев и документации — русский.**
- **Коммит после каждой задачи.**
- В коде уже есть проверенные приёмы, следуй им: секции конфигурации через
  словарь `sections` в `Config.from_dict`, переменные окружения через `mapping`
  в `_apply_env`, ступени схемы через `PRAGMA user_version` в `init_schema`.

**Механика проверена заранее** на этом окружении: `dataclasses.replace`
над `LLMConfig` сохраняет все настройки и меняет только модель, а `build_llm`
на копии даёт объект с новым именем (`ollama:b`); `field` уже импортирован
в `config.py`, а в `pipeline.py` строка импорта — `from dataclasses import
dataclass, field`, её надо дополнить `replace`, а не добавлять вторую.

---

### Задача 1: Список разрешённых моделей и его проверка

**Файлы:**
- Изменить: `ragkb/config.py` (поле `available` в `LLMConfig`)
- Создать: `ragkb/models.py`
- Создать: `tests/test_models.py`
- Изменить: `config.yaml`

**Интерфейсы:**
- Производит:
  - `LLMConfig.available: list[dict[str, str]]` — список `{"name": ..., "title": ...}`
  - `ragkb.models.available_models(cfg: LLMConfig) -> list[dict[str, str]]` —
    нормализованный список с пометкой выбранной по умолчанию
  - `ragkb.models.resolve_model(cfg: LLMConfig, requested: str | None) -> str` —
    возвращает имя модели либо поднимает `ValueError`

- [ ] **Шаг 1: Написать падающий тест**

Создать `tests/test_models.py`:

```python
"""Тесты выбора модели. Запуск: python tests/test_models.py"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ragkb.config import Config, LLMConfig
from ragkb.models import available_models, resolve_model


def _cfg() -> LLMConfig:
    return LLMConfig(
        model="qwen2.5:7b-instruct",
        available=[
            {"name": "qwen2.5:7b-instruct", "title": "Быстрая"},
            {"name": "qwen2.5:14b-instruct", "title": "Точная"},
        ],
    )


def test_available_models_marks_default():
    items = available_models(_cfg())
    assert [i["name"] for i in items] == ["qwen2.5:7b-instruct", "qwen2.5:14b-instruct"]
    assert items[0]["default"] is True
    assert items[1]["default"] is False


def test_available_models_without_list_returns_current():
    items = available_models(LLMConfig(model="что-то:latest"))
    assert len(items) == 1
    assert items[0]["name"] == "что-то:latest"
    assert items[0]["default"] is True


def test_available_models_fills_missing_title():
    items = available_models(LLMConfig(model="a", available=[{"name": "a"}]))
    assert items[0]["title"] == "a"


def test_resolve_model_returns_default_when_not_requested():
    assert resolve_model(_cfg(), None) == "qwen2.5:7b-instruct"
    assert resolve_model(_cfg(), "") == "qwen2.5:7b-instruct"


def test_resolve_model_accepts_allowed():
    assert resolve_model(_cfg(), "qwen2.5:14b-instruct") == "qwen2.5:14b-instruct"


def test_resolve_model_rejects_unknown():
    try:
        resolve_model(_cfg(), "злая:модель")
    except ValueError as exc:
        assert "злая:модель" in str(exc)
        return
    raise AssertionError("ожидался отказ для модели вне списка")


def test_resolve_model_without_list_rejects_anything_but_current():
    cfg = LLMConfig(model="только-эта")
    assert resolve_model(cfg, "только-эта") == "только-эта"
    try:
        resolve_model(cfg, "другая")
    except ValueError:
        return
    raise AssertionError("при пустом списке допустима только текущая модель")


def test_config_reads_available_from_dict():
    cfg = Config.from_dict({"llm": {"model": "a", "available": [{"name": "a", "title": "А"}]}})
    assert cfg.llm.available == [{"name": "a", "title": "А"}]


if __name__ == "__main__":
    failed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"  ok   {name}")
            except Exception as exc:
                failed += 1
                print(f"  FAIL {name}: {type(exc).__name__}: {exc}")
    print(f"\n{'все тесты пройдены' if not failed else f'провалов: {failed}'}")
    raise SystemExit(1 if failed else 0)
```

- [ ] **Шаг 2: Убедиться, что тест падает**

```bash
.venv/bin/python tests/test_models.py
```

Ожидается: `ModuleNotFoundError: No module named 'ragkb.models'`

- [ ] **Шаг 3: Добавить поле в `LLMConfig`**

В `ragkb/config.py`, в класс `LLMConfig`, после `timeout`:

```python
    # Список моделей, которые разрешено запрашивать. Пустой — переключения нет,
    # работает только model. Свободный ввод недопустим: незнакомое имя заставит
    # Ollama скачивать модель, а это десятки минут и место на диске по запросу
    # извне.
    available: list[dict[str, str]] = field(default_factory=list)
```

Убедись, что `field` уже импортирован из `dataclasses` в этом файле.

- [ ] **Шаг 4: Создать `ragkb/models.py`**

```python
"""Выбор генерирующей модели.

Имя модели приходит от клиента, поэтому проверяется по списку разрешённых:
передать его в Ollama как есть нельзя — незнакомое имя заставит её скачивать
модель, а это непредсказуемая задержка и заполнение диска по запросу извне.

Переключается только генерирующая модель. Эмбеддер заморожен индексом:
RAGPipeline._restore_embedder отказывается работать при расхождении, иначе
запрос и документы окажутся в разных векторных пространствах.
"""
from __future__ import annotations

from typing import Any

from .config import LLMConfig


def available_models(cfg: LLMConfig) -> list[dict[str, Any]]:
    """Нормализованный список моделей для интерфейса.

    Пустой available означает, что переключения нет: отдаём одну текущую.
    """
    entries = cfg.available or [{"name": cfg.model}]
    out: list[dict[str, Any]] = []
    for entry in entries:
        name = entry.get("name", "")
        if not name:
            continue
        out.append({
            "name": name,
            "title": entry.get("title") or name,
            "default": name == cfg.model,
        })
    return out


def resolve_model(cfg: LLMConfig, requested: str | None) -> str:
    """Проверяет запрошенное имя. Пустое означает «по умолчанию».

    Поднимает ValueError, если имя не разрешено — вызывающий код превращает
    это в отказ 400.
    """
    if not requested:
        return cfg.model
    allowed = {item["name"] for item in available_models(cfg)}
    if requested not in allowed:
        raise ValueError(
            f"Модель «{requested}» не разрешена. Доступны: {', '.join(sorted(allowed))}"
        )
    return requested
```

- [ ] **Шаг 5: Убедиться, что тесты проходят**

```bash
.venv/bin/python tests/test_models.py
```

Ожидается: 8 строк `ok`, затем `все тесты пройдены`.

- [ ] **Шаг 6: Дописать `config.yaml`**

В секцию `llm` добавить:

```yaml
  # Модели, которые разрешено выбирать в интерфейсе. Пустой список —
  # переключения нет, работает только model выше.
  available:
    - name: qwen2.5:7b-instruct
      title: Быстрая
    - name: qwen2.5:14b-instruct
      title: Точная
```

- [ ] **Шаг 7: Прогнать остальные наборы и линтеры**

```bash
.venv/bin/python tests/test_stream.py && .venv/bin/python tests/test_history.py \
  && .venv/bin/python tests/test_auth.py && .venv/bin/python tests/test_pipeline.py
.venv/bin/ruff check ragkb tests examples && .venv/bin/mypy ragkb
```

Ожидается: все наборы пройдены, `All checks passed!`, `Success`.

- [ ] **Шаг 8: Коммит**

```bash
git add ragkb/config.py ragkb/models.py tests/test_models.py config.yaml
git commit -m "Модели: список разрешённых и его проверка"
```

---

### Задача 2: Модель на конкретный запрос в пайплайне

**Файлы:**
- Изменить: `ragkb/pipeline.py` (`_llm_for`, `ask`, `stream_answer`)
- Изменить: `tests/test_models.py`

**Интерфейсы:**
- Потребляет: `resolve_model` из задачи 1 не нужен здесь — проверку делает
  слой HTTP. Пайплайн получает уже проверенное имя.
- Производит:
  - `RAGPipeline._llm_for(model: str | None) -> LLM`
  - `RAGPipeline.ask(..., model: str | None = None)`
  - `RAGPipeline.stream_answer(..., model: str | None = None)`
  - `Answer.llm_backend` содержит имя фактически использованной модели

- [ ] **Шаг 1: Написать падающие тесты**

Дописать в `tests/test_models.py` **перед** блоком `if __name__ == "__main__":`:

```python
# ------------------------------------------------- модель на запрос

import tempfile

from ragkb.pipeline import RAGPipeline, build_index

SAMPLE_DOC = (
    "# Политика\n\n## Отпуск\n\nЕжегодный отпуск составляет 28 календарных дней.\n"
)


def _pipeline() -> RAGPipeline:
    workdir = Path(tempfile.mkdtemp(prefix="ragkb-models-"))
    docs = workdir / "docs"
    docs.mkdir()
    (docs / "policy.md").write_text(SAMPLE_DOC, encoding="utf-8")
    cfg = Config(docs_dir=str(docs), index_dir=str(workdir / "index"))
    cfg.store.backend = "numpy"
    cfg.history.path = str(workdir / "history.sqlite3")
    build_index(cfg)
    return RAGPipeline(cfg)


def test_llm_for_returns_same_object_without_override():
    rag = _pipeline()
    assert rag._llm_for(None) is rag.llm
    assert rag._llm_for(rag.cfg.llm.model) is rag.llm


def test_llm_for_builds_new_llm_for_other_model():
    rag = _pipeline()
    other = rag._llm_for("другая-модель")
    assert other is not rag.llm
    assert "другая-модель" in other.name


def test_llm_for_keeps_backend_and_settings():
    rag = _pipeline()
    rag.cfg.llm.temperature = 0.7
    other = rag._llm_for("другая-модель")
    assert other.cfg.temperature == 0.7
    assert other.cfg.backend == rag.cfg.llm.backend


def test_ask_records_used_model():
    rag = _pipeline()
    answer = rag.ask("сколько дней отпуска?")
    assert answer.llm_backend == rag.llm.name


def test_stream_answer_accepts_model():
    rag = _pipeline()
    hits, stream = rag.stream_answer("сколько дней отпуска?", model=None)
    assert isinstance(hits, list)
    assert "".join(stream)
```

- [ ] **Шаг 2: Убедиться, что тесты падают**

```bash
.venv/bin/python tests/test_models.py
```

Ожидается: `AttributeError: 'RAGPipeline' object has no attribute '_llm_for'`

- [ ] **Шаг 3: Добавить `_llm_for`**

В `ragkb/pipeline.py`, в класс `RAGPipeline`, после `_restore_embedder`:

```python
    def _llm_for(self, model: str | None) -> LLM:
        """Объект LLM под конкретный запрос.

        Построение дёшево — это обёртка над настройками, сама модель грузится
        в Ollama при первом обращении. Поэтому держать пул объектов незачем.

        Имя модели сюда приходит уже проверенным по списку разрешённых:
        проверка живёт в слое HTTP, ближе к источнику недоверенных данных.
        """
        if not model or model == self.cfg.llm.model:
            return self.llm
        return build_llm(replace(self.cfg.llm, model=model))
```

Добавь в начало файла импорт:

```python
from dataclasses import dataclass, field, replace
```

Проверь, что `dataclass` и `field` уже импортируются оттуда, и дополни строку,
а не добавляй вторую.

- [ ] **Шаг 4: Провести модель через `ask`**

В `ragkb/pipeline.py`, в сигнатуру `ask`, добавить параметр после `expand`:

```python
        model: str | None = None,
```

В теле метода, сразу после `warnings: list[str] = []`, добавить:

```python
        llm = self._llm_for(model)
```

Затем заменить в теле `ask` все обращения `self.llm` на `llm`:
вызов переформулировки, генерацию ответа и оба места, где заполняется
`llm_backend=self.llm.name` — там должно стать `llm_backend=llm.name`.

Метод `_condense` тоже обращается к `self.llm`. Добавь ему параметр:

```python
    def _condense(self, question: str, history: list[tuple[str, str]],
                  llm: LLM | None = None) -> str | None:
```

и внутри используй `(llm or self.llm).generate(...)`. В `ask` передавай `llm`.

- [ ] **Шаг 5: Провести модель через `stream_answer`**

В сигнатуру `stream_answer` добавить параметр:

```python
        model: str | None = None,
```

В теле заменить `self.llm.stream(...)` на `self._llm_for(model).stream(...)`,
а вызов `self._condense(question, history)` — на
`self._condense(question, history, self._llm_for(model))`.

- [ ] **Шаг 6: Убедиться, что тесты проходят**

```bash
.venv/bin/python tests/test_models.py
```

Ожидается: 13 строк `ok`, затем `все тесты пройдены`.

- [ ] **Шаг 7: Прогнать остальные наборы и линтеры**

```bash
.venv/bin/python tests/test_stream.py && .venv/bin/python tests/test_history.py \
  && .venv/bin/python tests/test_auth.py && .venv/bin/python tests/test_pipeline.py
.venv/bin/ruff check ragkb tests examples && .venv/bin/mypy ragkb
```

- [ ] **Шаг 8: Коммит**

```bash
git add ragkb/pipeline.py tests/test_models.py
git commit -m "Модели: выбор модели на конкретный запрос в пайплайне"
```

---

### Задача 3: Столбец `model` в истории

**Файлы:**
- Изменить: `ragkb/history.py` (ступень схемы 3, `append`, `Message`)
- Изменить: `tests/test_models.py`

**Интерфейсы:**
- Производит:
  - `SCHEMA_VERSION = 3`
  - столбец `messages.model TEXT NOT NULL DEFAULT ''`
  - `HistoryStore.append(..., model: str = "")`
  - `Message.model: str` и ключ `model` в `Message.to_dict()`

- [ ] **Шаг 1: Написать падающие тесты**

Дописать в `tests/test_models.py` перед раннером:

```python
# ------------------------------------------------- хранение модели

from ragkb.history import SCHEMA_VERSION, HistoryStore, connect, init_schema


def _store() -> HistoryStore:
    return HistoryStore(Path(tempfile.mkdtemp(prefix="ragkb-mstore-")) / "h.sqlite3")


def test_schema_version_is_three():
    assert SCHEMA_VERSION == 3


def test_message_carries_model():
    store = _store()
    cid = store.create_conversation("ivanov", "тема")
    store.append(cid, "ivanov", "assistant", "ответ", model="qwen2.5:7b-instruct")
    messages = store.get_messages(cid, "ivanov")
    assert messages[0].model == "qwen2.5:7b-instruct"
    assert messages[0].to_dict()["model"] == "qwen2.5:7b-instruct"


def test_model_defaults_to_empty():
    store = _store()
    cid = store.create_conversation("ivanov", "тема")
    store.append(cid, "ivanov", "user", "вопрос")
    assert store.get_messages(cid, "ivanov")[0].model == ""


def test_step_three_adds_column_to_v2_database():
    """База версии 2 должна получить столбец, не потеряв сообщений."""
    path = Path(tempfile.mkdtemp(prefix="ragkb-v2-")) / "h.sqlite3"
    with connect(path) as conn:
        # Создаём схему без последней ступени, как она выглядела в версии 2.
        conn.executescript(
            "CREATE TABLE conversations (id TEXT PRIMARY KEY, user TEXT NOT NULL,"
            " title TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL,"
            " updated_at TEXT NOT NULL);"
            "CREATE TABLE messages (id INTEGER PRIMARY KEY AUTOINCREMENT,"
            " conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,"
            " role TEXT NOT NULL CHECK (role IN ('user','assistant')),"
            " text TEXT NOT NULL, sources_json TEXT NOT NULL DEFAULT '[]',"
            " created_at TEXT NOT NULL);"
            "CREATE TABLE cleanup_state (id INTEGER PRIMARY KEY CHECK (id = 1),"
            " last_run TEXT NOT NULL);"
            "INSERT INTO cleanup_state (id, last_run) VALUES (1, '1970-01-01T00:00:00+00:00');"
        )
        conn.execute(
            "INSERT INTO conversations VALUES ('c1','ivanov','тема','2026-01-01','2026-01-01')"
        )
        conn.execute(
            "INSERT INTO messages (conversation_id, role, text, created_at)"
            " VALUES ('c1','user','старое сообщение','2026-01-01')"
        )
        conn.execute("PRAGMA user_version = 2")

    with connect(path) as conn:
        init_schema(conn)
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 3
        row = conn.execute("SELECT text, model FROM messages").fetchone()
        assert row["text"] == "старое сообщение"
        assert row["model"] == ""
```

- [ ] **Шаг 2: Убедиться, что тесты падают**

```bash
.venv/bin/python tests/test_models.py
```

Ожидается: `AssertionError` на версии схемы и `TypeError` про неизвестный
параметр `model`.

- [ ] **Шаг 3: Добавить ступень схемы**

В `ragkb/history.py` поднять константу:

```python
SCHEMA_VERSION = 3
```

Рядом со схемой добавить ступень:

```python
# Ступень 3: чем получен ответ. Пустая строка — сообщение записано до появления
# выбора модели, интерфейс тогда ничего не показывает.
_SCHEMA_V3 = """
ALTER TABLE messages ADD COLUMN model TEXT NOT NULL DEFAULT '';
"""
```

В `init_schema`, после существующей ветки `if version < 2:`, добавить:

```python
    if version < 3:
        conn.executescript(_SCHEMA_V3)
        conn.execute("PRAGMA user_version = 3")
```

Убедись, что установку версии проставляет последняя применённая ступень,
а не первая — то есть каждая ветка ставит свой номер.

- [ ] **Шаг 4: Провести модель через `append` и `Message`**

В `Message` добавить поле после `sources`:

```python
    model: str = ""
```

и ключ в `to_dict()`:

```python
            "model": self.model,
```

В `append` добавить параметр после `sources`:

```python
        model: str = "",
```

и провести его в `INSERT`: столбец `model` в списке колонок, `?` в значениях,
`model` в кортеже параметров.

В `get_messages` добавить `model` в список выбираемых столбцов и в конструктор
`Message`.

- [ ] **Шаг 5: Убедиться, что тесты проходят**

```bash
.venv/bin/python tests/test_models.py
```

Ожидается: 17 строк `ok`.

- [ ] **Шаг 6: Прогнать остальные наборы и линтеры**

```bash
.venv/bin/python tests/test_stream.py && .venv/bin/python tests/test_history.py \
  && .venv/bin/python tests/test_auth.py && .venv/bin/python tests/test_pipeline.py
.venv/bin/ruff check ragkb tests examples && .venv/bin/mypy ragkb
```

Если существующая база `data/history.sqlite3` осталась от разработки, она
получит столбец при первом обращении — это и есть проверка лестницы на живой
базе. Убедись, что сервис поднимается: `.venv/bin/python -c "import ragkb.api"`.

- [ ] **Шаг 7: Коммит**

```bash
git add ragkb/history.py tests/test_models.py
git commit -m "Модели: столбец model в истории, ступень схемы 3"
```

---

### Задача 4: Эндпоинты принимают выбор

**Файлы:**
- Изменить: `ragkb/api.py` (`AskRequest`, `GET /models`, оба обработчика)
- Изменить: `tests/test_models.py`
- Изменить: `README.md`

**Интерфейсы:**
- Потребляет: `available_models`, `resolve_model` из задачи 1;
  `ask(model=)`, `stream_answer(model=)` из задачи 2;
  `append(model=)` из задачи 3.
- Производит:
  - `AskRequest.model: str | None`, `AskRequest.top_k: int | None` с границами
  - `GET /models`
  - в ответе `/ask` и в событии `done` появляется ключ `model`

- [ ] **Шаг 1: Написать падающие тесты**

Дописать в `tests/test_models.py` перед раннером:

```python
# ------------------------------------------------- эндпоинты

import json


def _client(available=None):
    from fastapi.testclient import TestClient

    from ragkb.api import create_app

    workdir = Path(tempfile.mkdtemp(prefix="ragkb-api-"))
    docs = workdir / "docs"
    docs.mkdir()
    (docs / "policy.md").write_text(SAMPLE_DOC, encoding="utf-8")
    cfg = Config(docs_dir=str(docs), index_dir=str(workdir / "index"))
    cfg.store.backend = "numpy"
    cfg.auth.mode = "disabled"
    cfg.history.path = str(workdir / "history.sqlite3")
    if available is not None:
        cfg.llm.available = available
    build_index(cfg)
    return TestClient(create_app(cfg), raise_server_exceptions=False), cfg


ALLOWED = [{"name": "extractive-a", "title": "А"}, {"name": "extractive-b", "title": "Б"}]


def test_models_endpoint_lists_allowed():
    client, cfg = _client(ALLOWED)
    body = client.get("/models").json()
    assert [m["name"] for m in body["models"]] == ["extractive-a", "extractive-b"]


def test_models_endpoint_requires_auth_when_enabled():
    from ragkb.api import create_app

    from fastapi.testclient import TestClient
    cfg = Config()
    cfg.auth.mode = "proxy"
    assert TestClient(create_app(cfg)).get("/models").status_code == 401


def test_ask_rejects_unknown_model():
    client, _ = _client(ALLOWED)
    resp = client.post("/ask", json={"question": "тест", "model": "злая:модель"})
    assert resp.status_code == 400, resp.status_code


def test_stream_rejects_unknown_model_before_streaming():
    client, _ = _client(ALLOWED)
    resp = client.post("/ask/stream", json={"question": "тест", "model": "злая:модель"})
    assert resp.status_code == 400, resp.status_code
    assert "ndjson" not in resp.headers.get("content-type", "")


def test_ask_accepts_allowed_model():
    client, cfg = _client(ALLOWED)
    cfg.llm.model = "extractive-a"
    body = client.post("/ask", json={"question": "сколько дней отпуска?",
                                     "model": "extractive-b"}).json()
    assert body["model"] == "extractive-b"


def test_stream_done_carries_model():
    client, _ = _client(ALLOWED)
    lines = client.post("/ask/stream", json={"question": "сколько дней отпуска?"}).text.splitlines()
    done = json.loads([line for line in lines if line.strip()][-1])
    assert done["type"] == "done"
    assert done["model"]


def test_top_k_out_of_range_gives_422():
    client, _ = _client()
    assert client.post("/ask", json={"question": "тест", "top_k": 0}).status_code == 422
    assert client.post("/ask", json={"question": "тест", "top_k": 99}).status_code == 422


def test_model_is_stored_with_message():
    from ragkb.history import HistoryStore

    client, cfg = _client(ALLOWED)
    body = client.post("/ask", json={"question": "сколько дней отпуска?",
                                     "model": "extractive-b"}).json()
    messages = HistoryStore(cfg.history.path).get_messages(body["conversation_id"], "anonymous")
    assert messages[1].model == "extractive-b"
```

- [ ] **Шаг 2: Убедиться, что тесты падают**

```bash
.venv/bin/python tests/test_models.py
```

Ожидается: `FAIL` — эндпоинта `/models` нет, поле `model` не принимается.

- [ ] **Шаг 3: Расширить `AskRequest`**

В `ragkb/api.py`:

```python
class AskRequest(BaseModel):
    question: str = Field(..., min_length=2)
    # Границы: ноль фрагментов бессмысленен, а больше двадцати не поместится
    # в разумный промпт. Число фрагментов — самый сильный рычаг скорости
    # на машине без ускорителя.
    top_k: int | None = Field(None, ge=1, le=20)
    expand: bool = False
    history: list[tuple[str, str]] = Field(default_factory=list)
    conversation_id: str | None = None
    # Пустое значение означает «модель по умолчанию из настроек».
    model: str | None = None
```

- [ ] **Шаг 4: Добавить `GET /models`**

В `ragkb/api.py`, рядом с остальными эндпоинтами:

```python
    @app.get("/models")
    def list_models(user: User = Depends(current_user)) -> dict[str, Any]:
        return {"models": available_models(cfg.llm)}
```

Добавь импорт в начало файла:

```python
from .models import available_models, resolve_model
```

- [ ] **Шаг 5: Провести выбор через `/ask`**

В обработчике `/ask`, самым первым действием, до обращения к истории:

```python
        try:
            model = resolve_model(cfg.llm, req.model)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
```

Передать `model=model` в вызов `pipeline().ask(...)`.

Передать `model=answer.llm_backend` во второй вызов `store.append` (тот,
что пишет реплику ассистента).

После `data = answer.to_dict()` добавить:

```python
        data["model"] = answer.llm_backend
```

- [ ] **Шаг 6: Провести выбор через `/ask/stream`**

В обработчике `/ask/stream` добавить ту же проверку самым первым действием —
до начала потока, чтобы отказ пришёл кодом, а не событием.

Передать `model=model` в вызов `rag.stream_answer(...)`.

Запомнить имя использованной модели до входа в генератор:

```python
        used_model = rag._llm_for(model).name
```

Передать `model=used_model` во второй `store.append` и добавить ключ в событие
`done`:

```python
                    "model": used_model,
```

- [ ] **Шаг 7: Убедиться, что тесты проходят**

```bash
.venv/bin/python tests/test_models.py
```

Ожидается: 25 строк `ok`.

- [ ] **Шаг 8: Описать в README**

В разделе про HTTP API дополнить таблицу строкой:

```markdown
| `GET /models` | список моделей, которые разрешено выбирать |
```

И добавить абзац:

```markdown
`POST /ask` и `POST /ask/stream` принимают необязательные `model` и `top_k`.
Имя модели проверяется по списку `llm.available` из `config.yaml`: свободный
ввод недопустим, иначе незнакомое имя заставит Ollama скачивать модель.
Пустой список означает, что переключения нет и работает `llm.model`.

Число фрагментов — самый сильный рычаг скорости на машине без ускорителя:
по замерам уменьшение с пяти до трёх сокращает время ответа примерно вдвое
при том же качестве.
```

- [ ] **Шаг 9: Прогнать всё и закоммитить**

```bash
.venv/bin/python tests/test_stream.py && .venv/bin/python tests/test_history.py \
  && .venv/bin/python tests/test_auth.py && .venv/bin/python tests/test_pipeline.py
.venv/bin/ruff check ragkb tests examples && .venv/bin/mypy ragkb
git add ragkb/api.py tests/test_models.py README.md
git commit -m "Модели: эндпоинты принимают выбор модели и числа фрагментов"
```

---

### Задача 5: Переключатели в интерфейсе

**Файлы:**
- Изменить: `ragkb/ui.py`

**Интерфейсы:**
- Потребляет: `GET /models` из задачи 4; ключ `model` в событии `done`
  и в сообщениях диалога.
- Производит: рабочие переключатели. Автоматическими тестами не покрывается.

- [ ] **Шаг 1: Добавить разметку переключателей**

В `ragkb/ui.py`, в `UI_HTML`, перед формой ввода вставить:

```html
  <div id="controls">
    <label>Модель <select id="model"></select></label>
    <label>Фрагментов <select id="topk">
      <option value="2">2</option>
      <option value="3">3</option>
      <option value="5" selected>5</option>
    </select></label>
  </div>
```

В блок `<style>` добавить:

```css
  #controls { display:flex; gap:16px; padding:8px 20px 0; font-size:13px;
              color:var(--muted); }
  #controls select { background:var(--bg); color:var(--fg);
              border:1px solid var(--line); border-radius:6px; padding:3px 6px; }
```

- [ ] **Шаг 2: Заполнить список моделей и запомнить выбор**

В `<script>`, после объявления `let currentId = null;`:

```js
const modelEl = document.getElementById('model');
const topkEl = document.getElementById('topk');

// Выбор помнит браузер: сервер намеренно без состояния везде, кроме истории.
function restoreChoice() {
  const m = localStorage.getItem('ragkb.model');
  const k = localStorage.getItem('ragkb.topk');
  if (m) modelEl.value = m;
  if (k) topkEl.value = k;
}
modelEl.addEventListener('change', () => localStorage.setItem('ragkb.model', modelEl.value));
topkEl.addEventListener('change', () => localStorage.setItem('ragkb.topk', topkEl.value));

async function loadModels() {
  try {
    const r = await fetch('/models');
    if (!r.ok) return;
    const items = (await r.json()).models || [];
    modelEl.innerHTML = '';
    items.forEach(m => {
      const o = document.createElement('option');
      o.value = m.name;
      o.textContent = m.title;
      if (m.default) o.selected = true;
      modelEl.appendChild(o);
    });
    restoreChoice();
  } catch (_) { /* список моделей не критичен: без него работает выбор по умолчанию */ }
}
```

- [ ] **Шаг 3: Подставлять выбор в запрос и показывать в ответе**

В обработчике отправки заменить тело запроса на:

```js
      body: JSON.stringify({
        question,
        conversation_id: currentId,
        model: modelEl.value || null,
        top_k: parseInt(topkEl.value, 10)
      })
```

В ветке события `done` заменить строку со временем на:

```js
          const label = ev.model ? `${esc(ev.model)} · ${esc(ev.elapsed_sec)} с`
                                 : `${esc(ev.elapsed_sec)} с`;
          box.insertAdjacentHTML('beforeend', `<div class="meta">${label}</div>`);
```

В `openConv`, при отрисовке сохранённых сообщений, показывать модель под
ответом ассистента: если у сообщения есть непустое поле `model`, добавить
`<div class="meta">` с ним.

- [ ] **Шаг 4: Предупреждать о пустом ответе**

В ветке `done` перед показом источников добавить:

```js
          if (!text.trim()) {
            box.insertAdjacentHTML('beforeend',
              '<div class="warn">⚠ Модель вернула пустой ответ</div>');
          }
```

- [ ] **Шаг 5: Вызвать загрузку моделей при старте**

В стартовом блоке, перед загрузкой списка диалогов, добавить `await loadModels();`

- [ ] **Шаг 6: Проверить программно**

```bash
cat > /tmp/check_ui.py <<'PY'
import sys
sys.path.insert(0, ".")
from fastapi.testclient import TestClient
from ragkb.api import create_app
from ragkb.config import Config

cfg = Config()
cfg.auth.mode = "disabled"
body = TestClient(create_app(cfg)).get("/").text
for marker in ['id="model"', 'id="topk"', "/models", "localStorage", "пустой ответ"]:
    assert marker in body, f"нет разметки: {marker}"
assert "indexOf('\\n')" in body, "экранирование перевода строки сломано"
print("разметка на месте")
PY
.venv/bin/python /tmp/check_ui.py && rm /tmp/check_ui.py
```

- [ ] **Шаг 7: Ручная проверка**

Требуется индекс и Ollama. Если их нет — отметь в отчёте, не выдумывай.

```bash
ollama serve &
RAGKB_AUTH_MODE=disabled .venv/bin/python -m ragkb.cli serve --port 8000
```

Сценарий:

1. В списке моделей видны названия из `config.yaml`
2. Задать вопрос — под ответом стоит имя использованной модели
3. Сменить модель, задать вопрос — под ответом другое имя
4. Перезагрузить страницу — выбор сохранился
5. Поставить фрагментов 2, задать вопрос — ответ заметно быстрее
6. Открыть старый диалог — под ответами видно, чем они получены

- [ ] **Шаг 8: Прогнать всё и закоммитить**

```bash
.venv/bin/python tests/test_models.py && .venv/bin/python tests/test_stream.py \
  && .venv/bin/python tests/test_history.py && .venv/bin/python tests/test_auth.py \
  && .venv/bin/python tests/test_pipeline.py
.venv/bin/ruff check ragkb tests examples && .venv/bin/mypy ragkb
git add ragkb/ui.py
git commit -m "Модели: переключатели модели и числа фрагментов в интерфейсе"
```

---

## Что остаётся за пределами этого плана

**Сверка списка с Ollama живьём** — открытый вопрос спеки. Список отдаётся
из конфигурации; модель, удалённая из Ollama и оставшаяся в настройках, даст
ошибку при первом обращении.

**Хранение выбора в диалоге, а не в браузере** — тогда возврат к старой
переписке восстанавливал бы и модель.

**Замена числа фрагментов на «быстро / точно»** — прятать и модель, и число
за одним понятным переключателем.

**Стриминг для `OpenAILLM`** — сейчас переопределён только у Ollama.
