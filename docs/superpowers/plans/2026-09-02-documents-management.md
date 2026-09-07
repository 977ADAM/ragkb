# Documents management in admin UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Страница админа `/admin/documents`: список файлов корпуса со статусом индексации, загрузка нового документа (multipart) с авто-переиндексацией, удаление документа (файл + индекс), правка compose (`data/docs` на запись), тесты бэкенда и ручной проход UI.

**Architecture:** Новый `DocumentsService` в `services/` (как `IndexService`: `(cfg, get_engine, invalidate)`), читает каталог `cfg.docs_dir` и манифест через движок; состояние файла считает по mtime и `built_at` манифеста. Ручки `/admin/documents` под `require_admin` (новый `api/routes/documents.py`). Удаление на chroma — точечно через `core/pipeline.remove_document`, на numpy — полная пересборка. UI ходит только в BFF `/api/admin/documents*`.

**Tech Stack:** FastAPI (UploadFile/File → нужен `python-multipart`), SvelteKit BFF, Docker Compose, pytest на numpy и sqlite-session.

**Спека:** `docs/superpowers/specs/2026-09-02-documents-management-design.md`

## Global Constraints

- Каталог корпуса — плоский: загрузка пишет файл в корень `docs_dir`, список строит по basename; вложенные каталоги и дубли имён — вне скоупа (корпус `data/docs` плоский). `loaders.discover` при этом остаётся общим фильтром «что индексируется».
- `built_at` (ISO UTC) пишется в манифест на верхний уровень только при полной сборке (`build_index` → `extra`). Точечное удаление (chroma) его не обновляет: оставшиеся файлы индексированы на момент `built_at`, это корректно. Старые манифесты без `built_at` → `built_at: null`, состояние только «в индексе» (`unknown`) / «нет».
- `POST /admin/documents` — одна синхронная операция, как существующая кнопка «Перестроить индекс»: сохранить файл → полный `build_index` → вернуть отчёт. `update_documents`/`update` не используются.
- Откат при загрузке: если `build_index` упал целиком (после загрузки не осталось ни одного документа: ValueError/FileNotFoundError) — только что сохранённый файл удаляется, ручка отвечает 400 с текстом. Индекс при этом не тронут (build_index падает до записи стора).
- Перезапись одноимённого файла разрешена (спека), UI предупреждает confirm'ом.
- DELETE: файла нет в каталоге → 404. Индекса нет (нет `manifest.json`) → удаляем только файл, 204. Chroma: `remove_document`; numpy: полная пересборка; если после удаления в `docs_dir` не осталось поддерживаемых файлов — индекс очищается целиком (каталог `index_dir`), статус становится `no_index`.
- Не-админ на ручках → 403 (роутер под `require_admin`, как `/admin/users`).
- `PayloadTooLarge` — новый класс в `core/errors.py`, маппинг 413 в `api/errors.py` (спека: лимит размера → 413).
- Лимит загрузки — константа `MAX_UPLOAD_BYTES = 20 * 1024 * 1024` в `services/documents.py`; роут читает не больше лимита+1 байта (память не разрастается).
- `python-multipart` добавить в `backend/pyproject.toml` (`uv add`), иначе `UploadFile` не работает.
- SQLAlchemy не импортировать в `ragkb/services/documents.py`; `ragkb.api.routes.documents.py` — без `ragkb.core` кроме `ragkb.core.errors` (тесты архитектуры это проверяют сами).
- Коммит после каждой задачи. Не пушить, пока не попросят. Исторические планы в `docs/superpowers/plans/` не переписывать.
- Compose: `./data/docs:/app/data/docs:ro` → без `:ro`. Остальные тома не трогаем.

## File map

**Создать**

- `backend/ragkb/services/documents.py`
- `backend/ragkb/api/routes/documents.py`
- `backend/tests/test_documents.py`
- `frontend/src/routes/api/admin/documents/+server.js`
- `frontend/src/routes/api/admin/documents/[name]/+server.js`
- `frontend/src/routes/admin/documents/+page.svelte`

**Менять**

- `backend/ragkb/core/pipeline.py` — `built_at` в `extra` у `build_index`
- `backend/ragkb/core/errors.py` — `PayloadTooLarge`
- `backend/ragkb/api/errors.py` — маппинг 413
- `backend/ragkb/api/router.py` — include documents под `/admin`
- `backend/ragkb/api/deps/services.py` — `documents_service`
- `backend/pyproject.toml` (+ `backend/uv.lock`) — `python-multipart`
- `docker-compose.yml` — том `data/docs` на запись
- `frontend/src/routes/admin/+layout.svelte` — пункт «Документы» в навигации
- `frontend/src/routes/admin/+page.svelte` — ссылка в хабе
- `README.md` (HTTP-таблица: `/admin/documents`; строка про `data/docs` на запись)
- `docs/superpowers/specs/2026-09-02-documents-management-design.md` — статус «готово» (задача 6)

---

### Task 1: `built_at` в манифесте

**Files:**
- Modify: `backend/ragkb/core/pipeline.py`
- Test: `backend/tests/test_documents.py` (первые два теста — или дописать в `test_pipeline.py` рядом с `_assert_end_to_end`)

**Interfaces:**
- Produces: манифест после `build_index` содержит верхнеуровневый `built_at` (ISO, UTC); старые манифесты без ключа читаются как есть.

- [ ] **Step 1: Write failing assertion**

В `test_pipeline.py` рядом с индексными тестами:

```python
def test_manifest_has_built_at():
    from ragkb.core.pipeline import build_index

    cfg = _workspace("numpy")
    build_index(cfg)
    manifest = json.loads((Path(cfg.index_dir) / "manifest.json").read_text(encoding="utf-8"))
    assert "built_at" in manifest
    from datetime import datetime
    datetime.fromisoformat(manifest["built_at"])  # не падает — валидный ISO
```

(`_workspace` и `_chroma_available` уже есть в файле; добавить `import json` если нет.)

- [ ] **Step 2: Run to see fail**

Run: `cd backend && uv run python -m pytest tests/test_pipeline.py::test_manifest_has_built_at -q`

Expected: FAIL — ключа `built_at` нет.

- [ ] **Step 3: Implement**

В `pipeline.py` в шапку добавить `from datetime import datetime, timezone` (проверить, нет ли уже). В `build_index` в `extra={...}` дописать:

```python
extra={
    "built_at": datetime.now(timezone.utc).isoformat(),
    "chunk_size": cfg.chunking.size,
    "chunk_overlap": cfg.chunking.overlap,
    "skipped": skipped,
},
```

`store._fill_manifest` уже раскладывает `extra` на верхний уровень манифеста — менять `store.py` не нужно.

- [ ] **Step 4: Tests pass**

Run: `cd backend && uv run python -m pytest tests/test_pipeline.py -q`

- [ ] **Step 5: Commit**

```bash
git add backend/ragkb/core/pipeline.py backend/tests/test_pipeline.py
git commit -m "Stamp built_at into index manifest on full rebuild."
```

---

### Task 2: `DocumentsService` (list / upload / delete)

**Files:**
- Create: `backend/ragkb/services/documents.py`
- Test: `backend/tests/test_documents.py` (юнит, numpy, без HTTP и без Postgres)

**Interfaces:**
- `MAX_UPLOAD_BYTES = 20 * 1024 * 1024`
- `DocumentsService(cfg: Config, get_engine: Callable[[], AnswerEngine], invalidate: Callable[[], None])`
- `list_documents() -> dict` — контракт спеки (docs_dir, index, built_at, corpus, orphans, skipped, summary)
- `upload(filename: str, content: bytes) -> dict` — отчёт как у `/index/rebuild`; `InvalidRequest` (расширение/имя), `PayloadTooLarge`, 400 с текстом при полном провале сборки
- `delete(name: str) -> None` — `NotFound` если файла нет
- Статусы файла: `indexed` | `new` | `stale` (mtime > built_at) | `unknown` (в индексе, built_at нет). Нет индекса → `index: "no_index"`, элементы `corpus` без статусов (`state: null`), `orphans`/`skipped` пустые, `built_at: null`.

- [ ] **Step 1: Failing unit tests (numpy)**

В `backend/tests/test_documents.py`. Конфиг — как в `test_pipeline._workspace`, но переиспользуем фикстуру-хелпер на tmp_path (БЕЗ `conftest.cfg`, чтобы не требовать Postgres):

```python
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import pytest

from ragkb.core.config import Config
from ragkb.core.errors import EngineUnavailable, InvalidRequest, NotFound, PayloadTooLarge
from ragkb.core.pipeline import RAGPipeline, build_index
from ragkb.services.documents import MAX_UPLOAD_BYTES, DocumentsService


def make_cfg(tmp_path: Path) -> Config:
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "policy.md").write_text(
        "# Политика\n\n## Отпуск\n\nЕжегодный отпуск составляет 28 календарных дней.\n",
        encoding="utf-8",
    )
    cfg = Config(docs_dir=str(docs), index_dir=str(tmp_path / "index"))
    cfg.store.backend = "numpy"
    return cfg


def make_service(cfg: Config) -> DocumentsService:
    def get_engine():
        try:
            return RAGPipeline(cfg)
        except (FileNotFoundError, ValueError) as exc:
            raise EngineUnavailable(str(exc)) from exc

    return DocumentsService(cfg, get_engine, lambda: None)
```

Тесты:

```python
def test_list_after_build(tmp_path):
    cfg = make_cfg(tmp_path)
    build_index(cfg)
    svc = make_service(cfg)
    body = svc.list_documents()
    assert body["index"] == "ok"
    assert body["built_at"] is not None
    assert len(body["corpus"]) == 1
    row = body["corpus"][0]
    assert row["name"] == "policy.md"
    assert row["indexed"] is True
    assert row["state"] == "indexed"
    assert row["chunks"] >= 1
    assert body["summary"]["corpus_files"] == 1
    assert body["orphans"] == []

def test_list_new_file_is_new(tmp_path):
    cfg = make_cfg(tmp_path)
    build_index(cfg)
    (Path(cfg.docs_dir) / "fresh.md").write_text("# Новый\n\nТекст.\n", encoding="utf-8")
    body = make_service(cfg).list_documents()
    by_name = {r["name"]: r for r in body["corpus"]}
    assert by_name["fresh.md"]["state"] == "new"
    assert by_name["fresh.md"]["indexed"] is False

def test_list_stale_when_mtime_newer(tmp_path):
    cfg = make_cfg(tmp_path)
    build_index(cfg)
    target = Path(cfg.docs_dir) / "policy.md"
    future = datetime.now(timezone.utc).timestamp() + 3600
    import os
    os.utime(target, (future, future))
    body = make_service(cfg).list_documents()
    row = next(r for r in body["corpus"] if r["name"] == "policy.md")
    assert row["state"] == "stale"

def test_list_orphan_when_file_removed(tmp_path):
    cfg = make_cfg(tmp_path)
    build_index(cfg)
    (Path(cfg.docs_dir) / "policy.md").unlink()
    body = make_service(cfg).list_documents()
    assert len(body["orphans"]) == 1
    assert body["orphans"][0]["source"].endswith("policy.md")

def test_list_no_index(tmp_path):
    cfg = make_cfg(tmp_path)  # индекс не собран
    body = make_service(cfg).list_documents()
    assert body["index"] == "no_index"
    assert body["built_at"] is None
    assert body["orphans"] == [] and body["skipped"] == []
    assert body["corpus"][0]["state"] is None

def test_upload_saves_file_and_reindexes(tmp_path):
    cfg = make_cfg(tmp_path)
    build_index(cfg)
    svc = make_service(cfg)
    report = svc.upload("new.md", b"# Новый\n\nПравило про отпуск: 28 дней.\n")
    assert report["files"] >= 1
    assert (Path(cfg.docs_dir) / "new.md").exists()
    body = svc.list_documents()
    assert len(body["corpus"]) == 2
    assert all(r["indexed"] for r in body["corpus"])

def test_upload_rejects_bad_extension(tmp_path):
    cfg = make_cfg(tmp_path)
    svc = make_service(cfg)
    with pytest.raises(InvalidRequest):
        svc.upload("evil.exe", b"x" * 10)

def test_upload_rejects_hidden_name(tmp_path):
    cfg = make_cfg(tmp_path)
    svc = make_service(cfg)
    with pytest.raises(InvalidRequest):
        svc.upload(".env", b"SECRET=1\n")

def test_upload_rolls_back_when_corpus_empty(tmp_path, monkeypatch):
    cfg = make_cfg(tmp_path)
    (Path(cfg.docs_dir) / "policy.md").unlink()
    svc = make_service(cfg)
    # файл с расширением, но без текста — build_index упадёт целиком
    with pytest.raises(InvalidRequest):
        svc.upload("scan.pdf", b"%PDF-1.4 no text layer")
    assert not (Path(cfg.docs_dir) / "scan.pdf").exists()

def test_upload_size_limit(tmp_path):
    cfg = make_cfg(tmp_path)
    svc = make_service(cfg)
    with pytest.raises(PayloadTooLarge):
        svc.upload("big.md", b"a" * (MAX_UPLOAD_BYTES + 1))

def test_delete_removes_file_and_index_entry(tmp_path):
    cfg = make_cfg(tmp_path)
    build_index(cfg)
    (Path(cfg.docs_dir) / "policy.md").write_text("# A\n\n## B\n\n" + "x" * 2000 + "\n", encoding="utf-8")
    # второй документ, чтобы после удаления корпус не опустел
    (Path(cfg.docs_dir) / "keep.md").write_text("# Keep\n\nТекст для чанка.\n", encoding="utf-8")
    build_index(cfg)
    svc = make_service(cfg)
    svc.delete("policy.md")
    assert not (Path(cfg.docs_dir) / "policy.md").exists()
    body = svc.list_documents()
    names = {r["name"] for r in body["corpus"]}
    assert "policy.md" not in names and "keep.md" in names

def test_delete_missing_file_is_404(tmp_path):
    cfg = make_cfg(tmp_path)
    build_index(cfg)
    with pytest.raises(NotFound):
        make_service(cfg).delete("nope.md")

def test_delete_last_doc_clears_index(tmp_path):
    cfg = make_cfg(tmp_path)
    build_index(cfg)
    make_service(cfg).delete("policy.md")
    body = make_service(cfg).list_documents()
    assert body["index"] == "no_index"
```

Не-админ/403 и multipart-роут — в задаче 3.

- [ ] **Step 2: Run to see fail**

Run: `cd backend && uv run python -m pytest tests/test_documents.py -q`

Expected: FAIL — `ragkb.services.documents` не существует (ImportError) / `PayloadTooLarge` нет.

- [ ] **Step 3: Implement service**

`ragkb/core/errors.py`:

```python
class PayloadTooLarge(RagkbError):
    pass
```

`ragkb/services/documents.py` — без fastapi/sqlalchemy:

```python
"""Состояние корпуса документов и операции над ним (загрузка/удаление)."""
from __future__ import annotations

import json
import shutil
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ragkb.core import loaders
from ragkb.core.config import Config
from ragkb.core.errors import EngineUnavailable, InvalidRequest, NotFound, PayloadTooLarge
from ragkb.core.pipeline import RAGPipeline, build_index, remove_document
from ragkb.core.ports import AnswerEngine
from ragkb.core.store import MANIFEST

MAX_UPLOAD_BYTES = 20 * 1024 * 1024

_HIDDEN_PREFIXES = (".", "~$")


class DocumentsService:
    def __init__(
        self,
        cfg: Config,
        get_engine: Callable[[], AnswerEngine],
        invalidate: Callable[[], None],
    ):
        self.cfg = cfg
        self._engine = get_engine
        self._invalidate = invalidate

    def list_documents(self) -> dict[str, Any]:
        docs_dir = Path(self.cfg.docs_dir)
        files = loaders.discover(docs_dir)
        try:
            manifest = self._engine().store.manifest
        except EngineUnavailable:
            return self._no_index_view(files)
        return self._view_with_index(files, manifest)

    def _no_index_view(self, files: list[Path]) -> dict[str, Any]:
        return {
            "docs_dir": str(Path(self.cfg.docs_dir)),
            "index": "no_index",
            "built_at": None,
            "corpus": [_file_row(f) for f in files],  # state: null
            "orphans": [],
            "skipped": [],
            "summary": {"corpus_files": len(files), "indexed_docs": 0, "chunks": 0},
        }

    def _view_with_index(self, files: list[Path], manifest: dict[str, Any]) -> dict[str, Any]:
        built_at_raw = manifest.get("built_at")
        built_at = None
        if built_at_raw:
            try:
                built_at = datetime.fromisoformat(built_at_raw)
            except ValueError:
                built_at = None
        docs_by_name = {Path(d["source"]).name: d for d in manifest.get("documents", [])}

        corpus = []
        matched = 0
        total_chunks = 0
        for f in files:
            entry = docs_by_name.get(f.name)
            row = _file_row(f)
            if entry is None:
                corpus.append({**row, "indexed": False, "chunks": 0, "state": "new"})
                continue
            matched += 1
            total_chunks += int(entry.get("chunks", 0))
            state = "indexed"
            if built_at is None:
                state = "unknown"
            else:
                mtime = datetime.fromtimestamp(f.stat().st_mtime, tz=timezone.utc)
                if mtime > built_at:
                    state = "stale"
            corpus.append({**row, "indexed": True, "chunks": entry.get("chunks", 0), "state": state})

        file_names = {f.name for f in files}
        orphans = [
            {k: d.get(k) for k in ("title", "source", "chunks")}
            for d in manifest.get("documents", [])
            if Path(d["source"]).name not in file_names
        ]
        return {
            "docs_dir": str(Path(self.cfg.docs_dir)),
            "index": "ok",
            "built_at": built_at_raw,
            "corpus": corpus,
            "orphans": orphans,
            "skipped": list(manifest.get("skipped", [])),
            "summary": {
                "corpus_files": len(files),
                "indexed_docs": matched,
                "chunks": total_chunks,
            },
        }

    def upload(self, filename: str, content: bytes) -> dict[str, Any]:
        name = Path(filename).name
        if not name or name.startswith(_HIDDEN_PREFIXES):
            raise InvalidRequest("Недопустимое имя файла")
        suffix = Path(name).suffix.lower()
        if suffix not in loaders.SUPPORTED_EXTENSIONS:
            raise InvalidRequest(
                f"Формат не поддерживается: {suffix or '(без расширения)'}. "
                f"Допустимы: {', '.join(sorted(loaders.SUPPORTED_EXTENSIONS))}"
            )
        if len(content) > MAX_UPLOAD_BYTES:
            raise PayloadTooLarge(
                f"Файл больше {MAX_UPLOAD_BYTES // (1024 * 1024)} МБ"
            )
        docs_dir = Path(self.cfg.docs_dir)
        docs_dir.mkdir(parents=True, exist_ok=True)
        target = docs_dir / name
        target.write_bytes(content)
        try:
            report = build_index(self.cfg)
        except (ValueError, FileNotFoundError) as exc:
            # Корпус после загрузки пуст (файл не дал текста) — откатываем файл.
            target.unlink(missing_ok=True)
            raise InvalidRequest(f"Не удалось проиндексировать: {exc}") from exc
        self._invalidate()
        return {
            "files": report.files,
            "chunks": report.chunks,
            "skipped": report.skipped,
            "elapsed_sec": round(report.elapsed, 1),
        }

    def delete(self, name: str) -> None:
        safe = Path(name).name
        target = Path(self.cfg.docs_dir) / safe
        if not target.is_file():
            raise NotFound(f"Файл «{safe}» не найден в каталоге документов")
        target.unlink()
        manifest_path = Path(self.cfg.index_dir) / MANIFEST
        if not manifest_path.exists():
            self._invalidate()
            return
        if self.cfg.store.backend.lower() == "chroma":
            remove_document(self.cfg, str(target))
        else:
            remaining = loaders.discover(Path(self.cfg.docs_dir))
            if not remaining:
                shutil.rmtree(Path(self.cfg.index_dir), ignore_errors=True)
            else:
                try:
                    build_index(self.cfg)
                except ValueError as exc:
                    raise InvalidRequest(f"Не удалось пересобрать индекс: {exc}") from exc
        self._invalidate()


def _file_row(path: Path) -> dict[str, Any]:
    stat = path.stat()
    return {
        "name": path.name,
        "size": stat.st_size,
        "mtime": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
    }
```

Тонкости, которые надо проверить реализатору:

- `loaders.discover(docs_dir)` при отсутствующем каталоге возвращает `[]` (rglob по несуществующему пути) — убедиться, что не бросает; иначе `_no_index_view` должен сам обрабатывать отсутствие каталога.
- Соответствие manifest-записи файлу — по basename `source` (корпус плоский, см. Constraints). `_document_summary` в `store.py` кладёт `source` как путь, по которому грузился файл.
- chroma-ветка `delete` работает только когда chroma установлена и индекс собран chroma — покрыть условным тестом как в `test_pipeline` (`_chroma_available`, pytest.skip), см. шаг 4.
- `MANIFEST` импортируется из `ragkb.core.store` — это разрешённый импорт core в services (архитектурный тест запрещает services→db/http, не services→core).

- [ ] **Step 4: Tests pass (numpy + chroma conditional)**

Добавить chroma-тест удаления:

```python
def test_delete_on_chroma_is_point_removal(tmp_path):
    pytest.importorskip("chromadb")
    cfg = make_cfg(tmp_path)
    cfg.store.backend = "chroma"
    build_index(cfg)
    (Path(cfg.docs_dir) / "keep.md").write_text("# Keep\n\nТекст.\n", encoding="utf-8")
    build_index(cfg)
    make_service(cfg).delete("keep.md")
    body = make_service(cfg).list_documents()
    assert all(r["name"] != "keep.md" for r in body["corpus"])
```

Run: `cd backend && uv run python -m pytest tests/test_documents.py -q`

Ожидание: numpy-тесты зелёные; chroma-тест прогоняется если chromadb стоит в окружении, иначе skip. Прогнать также `tests/test_architecture.py` — сервис не должен нарушить правила слоёв.

- [ ] **Step 5: Commit**

```bash
git add backend/ragkb/core/errors.py backend/ragkb/services/documents.py backend/tests/test_documents.py
git commit -m "Add DocumentsService: corpus state, upload, delete."
```

---

### Task 3: HTTP `/admin/documents` + deps + python-multipart

**Files:**
- Create: `backend/ragkb/api/routes/documents.py`
- Modify: `backend/ragkb/api/router.py`
- Modify: `backend/ragkb/api/deps/services.py`
- Modify: `backend/ragkb/api/errors.py` (маппинг 413)
- Modify: `backend/pyproject.toml` (+ `backend/uv.lock`) — `python-multipart`
- Test: `backend/tests/test_documents.py` (HTTP-часть: session sqlite)

**Interfaces:**
- `GET /admin/documents` → словарь списка (сервис)
- `POST /admin/documents` — multipart, поле `file`; 200 с отчётом `{files, chunks, skipped, elapsed_sec}`; 400/413/404 по правилам сервиса
- `DELETE /admin/documents/{name}` → 204; 404 если файла нет
- Все три — только админ (403 для `user`)

- [ ] **Step 1: Failing HTTP tests (session sqlite, как в test_admin_http)**

Добавить в `backend/tests/test_documents.py`. Фикстуры-хелперы по образцу `test_admin_http.py` (`_migrate_sqlite`, `sqlite_url`, `_seed_admin_and_user`, `_session_cfg`, `_signin`) — продублировать локально либо вынести общий хелпер; локальное дублирование предпочтительнее, чем трогать чужой тест-файл.

```python
def _session_client_cfg(tmp_path: Path, url: str) -> Config:
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "policy.md").write_text("# Политика\n\nТекст про отпуск: 28 дней.\n", encoding="utf-8")
    cfg = Config(
        docs_dir=str(docs),
        index_dir=str(tmp_path / "index"),
        organization=OrganizationConfig(name="Acme", id="acme"),
    )
    cfg.store.backend = "numpy"
    cfg.database_url = url
    cfg.auth.mode = "session"
    cfg.history.enabled = True
    cfg.logging.dir = str(tmp_path / "logs")
    return cfg


def test_non_admin_forbidden_on_documents(tmp_path, sqlite_url):
    cfg = _session_client_cfg(tmp_path, sqlite_url)
    with TestClient(create_app(cfg)) as client:
        _signin(client, "bob")
        assert client.get("/admin/documents").status_code == 403
        assert client.post("/admin/documents", files={"file": ("x.md", b"# X", "text/markdown")}).status_code == 403
        assert client.delete("/admin/documents/x.md").status_code == 403


def test_admin_gets_document_list(tmp_path, sqlite_url):
    cfg = _session_client_cfg(tmp_path, sqlite_url)
    with TestClient(create_app(cfg)) as client:
        _signin(client, "ada")
        body = client.get("/admin/documents").json()
        assert body["index"] == "no_index"
        assert body["corpus"][0]["name"] == "policy.md"


def test_admin_upload_and_list(tmp_path, sqlite_url):
    cfg = _session_client_cfg(tmp_path, sqlite_url)
    with TestClient(create_app(cfg)) as client:
        _signin(client, "ada")
        res = client.post(
            "/admin/documents",
            files={"file": ("new.md", b"# Новый\n\nПравило: 28 дней.\n", "text/markdown")},
        )
        assert res.status_code == 200
        assert res.json()["chunks"] >= 1
        body = client.get("/admin/documents").json()
        assert body["index"] == "ok"
        assert len(body["corpus"]) == 2


def test_admin_upload_bad_extension_is_400(tmp_path, sqlite_url):
    cfg = _session_client_cfg(tmp_path, sqlite_url)
    with TestClient(create_app(cfg)) as client:
        _signin(client, "ada")
        res = client.post("/admin/documents", files={"file": ("evil.exe", b"x", "application/octet-stream")})
        assert res.status_code == 400


def test_admin_upload_too_large_is_413(tmp_path, sqlite_url, monkeypatch):
    import ragkb.services.documents as documents_module
    monkeypatch.setattr(documents_module, "MAX_UPLOAD_BYTES", 10)
    cfg = _session_client_cfg(tmp_path, sqlite_url)
    with TestClient(create_app(cfg)) as client:
        _signin(client, "ada")
        res = client.post("/admin/documents", files={"file": ("big.md", b"a" * 20, "text/markdown")})
        assert res.status_code == 413


def test_admin_delete(tmp_path, sqlite_url):
    cfg = _session_client_cfg(tmp_path, sqlite_url)
    with TestClient(create_app(cfg)) as client:
        _signin(client, "ada")
        client.post("/admin/documents", files={"file": ("new.md", b"# N\n\nТекст.\n", "text/markdown")})
        res = client.delete("/admin/documents/new.md")
        assert res.status_code == 204
        assert client.delete("/admin/documents/new.md").status_code == 404
```

Внимание на `_admin_client`/`_session_cfg`/`sqlite_url` из `test_admin_http.py`: там `cfg.auth.mode = "session"` и сидятся ada(admin)/bob(user). Импортировать константы из соседнего тест-файла не стоит — продублировать хелперы (или вынести в `tests/helpers.py`, если дублирование большое; предпочесть хелперы в helpers.py).

- [ ] **Step 2: Run to see fail**

Run: `cd backend && uv run python -m pytest tests/test_documents.py -q`

Expected: FAIL — роутов нет, `python-multipart` не установлен.

- [ ] **Step 3: Implement**

Сначала зависимость:

```bash
cd backend && uv add python-multipart
```

(обновит `pyproject.toml` и `uv.lock`; FastAPI требует этот пакет для `UploadFile`).

`api/errors.py` — в `_STATUS`:

```python
PayloadTooLarge: 413,
```

(добавить в импорт из `ragkb.core.errors`).

`api/routes/documents.py`:

```python
"""HTTP-слой управления документами корпуса (админ)."""
from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, File, UploadFile

from ragkb.api.deps.auth import require_admin
from ragkb.api.deps.services import documents_service
from ragkb.services.documents import MAX_UPLOAD_BYTES, DocumentsService

log = logging.getLogger("ragkb")

router = APIRouter(dependencies=[Depends(require_admin)])

DocsService = Annotated[DocumentsService, Depends(documents_service)]


@router.get("/documents")
def list_documents(svc: DocsService) -> dict:
    return svc.list_documents()


@router.post("/documents")
async def upload_document(
    svc: DocsService,
    file: UploadFile = File(...),
) -> dict:
    # Читаем не больше лимита+1 байта: память не растёт с размером файла.
    content = await file.read(MAX_UPLOAD_BYTES + 1)
    result = svc.upload(file.filename or "", content)
    log.info("админ: загружен документ %s (%s чанков)", file.filename, result["chunks"])
    return result


@router.delete("/documents/{name}", status_code=204)
def delete_document(name: str, svc: DocsService) -> None:
    svc.delete(name)
    log.info("админ: удалён документ %s", name)
```

`api/deps/services.py`:

```python
from ragkb.services.documents import DocumentsService

def documents_service(request: Request) -> DocumentsService:
    c = container(request)
    return DocumentsService(c.cfg, c.engine, c.invalidate_engine)
```

`api/router.py`: импорт `documents` в списке routes и

```python
api_router.include_router(documents.router, prefix="/admin", tags=["admin"])
```

- [ ] **Step 4: Tests pass**

Run: `cd backend && uv run python -m pytest tests/test_documents.py tests/test_admin_http.py -q`

Замечание: если chroma стоит и какой-то тест открывает встроенную Chroma на общем `data/index`, тесты tmp_path изолированы — конфликтов не ждём. Прогнать и `tests/test_architecture.py` (routes не импортируют `ragkb.core` кроме errors — `api/routes/documents.py` не должен импортировать `ragkb.core.*`).

- [ ] **Step 5: Commit**

```bash
git add backend/ragkb/api backend/pyproject.toml backend/uv.lock backend/tests/test_documents.py
git commit -m "Add admin document routes with multipart upload."
```

---

### Task 4: Compose — `data/docs` на запись

**Files:**
- Modify: `docker-compose.yml`

- [ ] **Step 1: Реализовать**

В сервисе `rag`, том:

```yaml
      - ./data/docs:/app/data/docs:ro
```

→

```yaml
      - ./data/docs:/app/data/docs
```

Остальные тома (`data/logs`, `rag_index`, `rag_hf`) не трогаем. `rag` уже владеет записью индекса (`rag_index`), добавление записи в `docs` ничего не ломает: образ монтирует каталог поверх образа, права на хосте у пользователя с Docker.

- [ ] **Step 2: Проверка**

Если Docker доступен: `docker compose config | grep -A2 "data/docs"` — в выводе `:ro` отсутствует, `read_only` не задан. Иначе — проверка глазами по diff.

- [ ] **Step 3: Commit**

```bash
git add docker-compose.yml
git commit -m "Make corpus docs dir writable in compose for uploads."
```

---

### Task 5: BFF и UI

**Files:**
- Create: `frontend/src/routes/api/admin/documents/+server.js`
- Create: `frontend/src/routes/api/admin/documents/[name]/+server.js`
- Create: `frontend/src/routes/admin/documents/+page.svelte`
- Modify: `frontend/src/routes/admin/+layout.svelte` — nav
- Modify: `frontend/src/routes/admin/+page.svelte` — ссылка в хабе

**Interfaces:**
- GET/POST `/api/admin/documents`, DELETE `/api/admin/documents/[name]` — только админ (backend 403 идёт насквозь, hooks уже закрывают `/admin/**` для не-админов)
- multipart POST: BFF передаёт тело и `content-type` (с boundary) как есть — `backend()` кладёт свои заголовки поверх identity, но content-type из `init.headers` должен перебить `application/json`

- [ ] **Step 1: `bun run check` до изменений (базовая линия)**

Run: `cd frontend && bun run check`

- [ ] **Step 2: BFF routes**

`frontend/src/routes/api/admin/documents/+server.js`:

```js
import { json } from '@sveltejs/kit';
import { backend, failureText, unreachable } from '$lib/server/backend.js';

export function GET({ request }) {
	return proxyDocuments(request, { method: 'GET' });
}

export async function POST({ request }) {
	// Передаём multipart как есть: тело + исходный content-type (с boundary).
	const contentType = request.headers.get('content-type') ?? 'application/octet-stream';
	return proxyDocuments(request, {
		method: 'POST',
		headers: { 'content-type': contentType },
		body: await request.arrayBuffer()
	});
}

async function proxyDocuments(request, init) {
	let upstream;
	try {
		upstream = await backend('/admin/documents', request, init);
	} catch (error) {
		return json({ detail: unreachable(error) }, { status: 502 });
	}
	if (!upstream.ok) {
		return json({ detail: await failureText(upstream) }, { status: upstream.status });
	}
	return json(await upstream.json());
}
```

`frontend/src/routes/api/admin/documents/[name]/+server.js`:

```js
import { json } from '@sveltejs/kit';
import { backend, failureText, unreachable } from '$lib/server/backend.js';

export async function DELETE({ request, params }) {
	const path = `/admin/documents/${encodeURIComponent(params.name)}`;
	let upstream;
	try {
		upstream = await backend(path, request, { method: 'DELETE' });
	} catch (error) {
		return json({ detail: unreachable(error) }, { status: 502 });
	}
	if (!upstream.ok) {
		return json({ detail: await failureText(upstream) }, { status: upstream.status });
	}
	return new Response(null, { status: 204 });
}
```

Проверить, что в `backend.js` merge заголовков `{ ...identity(request), ...init.headers }` — `content-type` из `init` перебивает `application/json` из identity (так оно и есть). `SvelteKit` читает `request.arrayBuffer()` в POST — тело multipart не теряется.

- [ ] **Step 3: Страница `/admin/documents`**

По образцу `admin/users/+page.svelte` (Svelte 5 runes, `onMount`): шапка `Документы`, счётчик из `summary`, кнопка «Загрузить» с `<input type="file">`, таблица:

- столбцы: имя, состояние, размер, изменён, чанков, действие «Удалить» (confirm; disabled пока идёт операция);
- статусы: `indexed` → «в индексе», `new` → «новый, не проиндексирован», `stale` → «изменён, нужна переиндексация», `unknown` → «в индексе (дата неизвестна)», `null`/нет индекса → «индекс не собран»;
- блок «Сироты» (`orphans`): название/источник/чанки + подпись «документа нет в каталоге — исчезнет при полной переиндексации»;
- блок «Пропущено при сборке» (`skipped`): путь + причина;
- переиндексация на время `POST`/`DELETE`: кнопки disabled + «Индексация…»; после ответа — перечитать список;
- сообщение об ошибке строкой (detail из BFF), как на других админ-страницах.

Загрузка: `FormData` c полем `file`; перед отправкой, если файл с таким именем уже есть в `corpus`, — `confirm('Файл существует — перезаписать?')`.

- [ ] **Step 4: Ссылки**

`admin/+layout.svelte` nav: `<a href="/admin/documents">Документы</a>`. `admin/+page.svelte` (хаб): ссылка `· <a href="/admin/documents">Документы</a>` в ряду ссылок.

- [ ] **Step 5: `bun run check` + ручной проход**

Run: `cd frontend && bun run check` — без новых ошибок.

Ручной проход (по образцу admin-closeout): поднять бэкенд так, чтобы `cfg.docs_dir` указывал на каталог с файлами и индекс собирался (`make backend`, при необходимости `RAGKB_DOCS_DIR=…`/`RAGKB_INDEX_DIR=…`), фронт `bun run dev`; войти админом; `/admin` → «Документы»; убедиться: список файлов со статусами после переиндексации; загрузка `.md` → файл появился, статус indexed, счётчик чанков вырос; перезапись с confirm; удаление с confirm → файл исчез; «сирота» показывается после удаления файла вручную; не-админ на `/admin/documents` → редирект/403.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/routes/api/admin/documents frontend/src/routes/admin/documents frontend/src/routes/admin/+layout.svelte frontend/src/routes/admin/+page.svelte
git commit -m "Add admin documents page with upload and delete."
```

---

### Task 6: Доки и статус спеки

**Files:**
- Modify: `README.md`
- Modify: `docs/superpowers/specs/2026-09-02-documents-management-design.md`

- [ ] **Step 1: README**

В таблицу HTTP API (секция «HTTP API») добавить строки после `/admin/*`-семейства или в общую таблицу:

| `GET /admin/documents` | список файлов корпуса со статусом индексации (админ) |
| `POST /admin/documents` | загрузка документа multipart + переиндексация (админ) |
| `DELETE /admin/documents/{name}` | удаление документа: файл + индекс (админ) |

В «Боевую конфигурацию»/compose-блок (там, где про `./data/docs:/app/data/docs:ro`) — заменить `:ro` на запись и дописать: каталог корпуса смонтирован на запись для загрузки документов админом через UI.

- [ ] **Step 2: Спека**

`docs/superpowers/specs/2026-09-02-documents-management-design.md`: статус «в работе» → «готово».

- [ ] **Step 3: Финальный прогон**

Run: `cd backend && uv run python -m pytest tests/test_documents.py tests/test_architecture.py -q` и `cd frontend && bun run check`.

- [ ] **Step 4: Commit**

```bash
git add README.md docs/superpowers/specs/2026-09-02-documents-management-design.md
git commit -m "Document admin document endpoints and mark spec done."
```

---

## Spec coverage

| Спека | Задача |
|---|---|
| `built_at` в манифесте (extra при build_index) | 1 |
| два состояния (файл/манифест), state indexed/new/stale/unknown | 2 |
| orphans / skipped / summary / no_index | 2 |
| upload: multipart, перезапись, лимит 413, откат при пустом корпусе | 2, 3 |
| delete: файл + индекс, chroma точечно / иначе пересборка, 404/204 | 2, 3 |
| `/admin/documents` под require_admin, 403 не-админу | 3 |
| compose `:ro` → запись | 4 |
| BFF + страница `/admin/documents`, ссылка в хабе | 5 |
| тесты бэкенда; архитектура services/documents без HTTP/ORM | 2, 3 |
| фронт: ручной проход + `bun run check` | 5 |
| README + статус спеки | 6 |
