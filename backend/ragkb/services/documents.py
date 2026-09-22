"""Корпус документов: реестр, состояние и операции над файлами.

Реестр (таблица `corpus_documents`) — единственный источник документов:
попасть в базу знаний можно только загрузкой через страницу «Документы».
Файлы, положенные в каталог мимо интерфейса, не индексируются и в списке
не показываются — каталог не обходится вовсе. Без реестра (нет
`RAGKB_DATABASE_URL`) операции недоступны: загружать документы некуда.
"""
from __future__ import annotations

import asyncio
import hashlib
import os
import stat
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from ragkb.core import loaders
from ragkb.core.config import Settings
from ragkb.core.errors import EngineUnavailable, InvalidRequest, NotFound, PayloadTooLarge
from ragkb.core.ports import IndexEngine
from ragkb.domain.entities import ORIGIN_UI, CorpusDocument, RecordOutcome
from ragkb.domain.ports import DocumentRegistry

MAX_UPLOAD_BYTES = 20 * 1024 * 1024

_HIDDEN_PREFIXES = (".", "~$")

# Один текст на все операции без реестра: документы берутся только из него,
# поэтому без базы знаний работать не с чем — и это надо сказать прямо.
_NO_REGISTRY = (
    "Реестр документов не подключён: задайте RAGKB_DATABASE_URL. "
    "Документы добавляются только загрузкой через эту страницу."
)


@dataclass(frozen=True)
class UploadResult:
    """Итог загрузки: ответ для интерфейса и сведения для журнала.

    Прежнее и текущее разрешение на выдачу оригинала берутся из самой записи
    реестра, поэтому журнал не может показать устаревшее «старое» значение.
    Наружу уходит только `payload`.
    """

    payload: dict[str, Any]
    document_id: str
    created: bool
    previous_download_allowed: bool
    download_allowed: bool

    @property
    def replaced(self) -> bool:
        return not self.created


class DocumentsService:
    def __init__(
        self,
        cfg: Settings,
        index: IndexEngine,
        invalidate: Callable[[], None],
        registry: DocumentRegistry | None = None,
    ):
        self.cfg = cfg
        self._index = index
        self._invalidate = invalidate
        self._registry = registry

    @property
    def registry_enabled(self) -> bool:
        return self._registry is not None

    # ------------------------------------------------------------- состояние

    async def list_documents(self) -> dict[str, Any]:
        docs_dir = Path(self.cfg.docs_dir)
        registry = await self._rows()
        try:
            manifest = self._index.manifest()
        except EngineUnavailable:
            return self._view(docs_dir, registry, manifest=None)
        return self._view(docs_dir, registry, manifest=manifest)

    async def _rows(self) -> dict[str, CorpusDocument]:
        if self._registry is None:
            return {}
        return {doc.name: doc for doc in await self._registry.list_all()}

    def _view(
        self,
        docs_dir: Path,
        registry: dict[str, CorpusDocument],
        *,
        manifest: dict[str, Any] | None,
    ) -> dict[str, Any]:
        built_at_raw = (manifest or {}).get("built_at")
        built_at = _parse_ts(built_at_raw)
        documents = (manifest or {}).get("documents", [])
        # Путь надёжнее имени: два каталога корпуса могут содержать файлы
        # с одинаковым именем, а манифест хранит именно путь.
        by_source = {d.get("source", ""): d for d in documents}
        by_name = {Path(d.get("source", "")).name: d for d in documents}

        corpus: list[dict[str, Any]] = []
        indexed_docs = 0
        total_chunks = 0
        for name in sorted(registry):
            target = _document_file(docs_dir, name)
            exists = target.is_file()
            document = registry[name]
            row = _file_row(target, name, document) if exists else _missing_row(name, document)
            entry = by_source.get(str(target)) or by_name.get(Path(name).name)
            if entry is not None:
                indexed_docs += 1
                total_chunks += int(entry.get("chunks", 0))
            corpus.append(
                {
                    **row,
                    **_registry_fields(registry, name),
                    "indexed": entry is not None,
                    "chunks": entry.get("chunks", 0) if entry else 0,
                    "state": _file_state(
                        target,
                        row,
                        entry,
                        built_at,
                        exists=exists,
                        has_index=manifest is not None,
                    ),
                }
            )

        return {
            "docs_dir": str(docs_dir.expanduser().resolve()),
            "index": "ok" if manifest is not None else "no_index",
            "registry": "on" if self._registry is not None else "off",
            "built_at": built_at_raw,
            "corpus": corpus,
            "skipped": list((manifest or {}).get("skipped", [])),
            "summary": {
                "corpus_files": len(registry),
                "indexed_docs": indexed_docs,
                "chunks": total_chunks,
            },
        }

    # -------------------------------------------------------------- операции

    async def upload(
        self,
        filename: str,
        content: bytes,
        user: str = "",
        *,
        index: bool = True,
        download_allowed: bool = False,
    ) -> UploadResult:
        """Сохраняет документ и заводит его в реестре.

        `index=False` — файл только принимается: так грузится пачка, и одну
        индексацию делают в конце, а не после каждого файла.
        `download_allowed` — разрешение на выдачу оригинала; по умолчанию
        выключено, а при замене файла берётся из этого вызова, а не из
        прежней записи.
        """
        if self._registry is None:
            raise InvalidRequest(_NO_REGISTRY)
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
        # Новый контент сначала лежит во временном файле рядом: пока запись
        # реестра не сохранена, публиковать нечего, и отказ записи оставляет
        # и прежний файл, и прежнее разрешение нетронутыми.
        staged = docs_dir / f".{uuid4().hex}.upload"
        try:
            staged.write_bytes(content)
            if target.exists():
                # Режим доступа прежнего файла сохраняем: замена не должна
                # молча его менять.
                os.chmod(staged, stat.S_IMODE(target.stat().st_mode))
            # Одно изменение разрешения вместо «снять и выдать заново»: пара
            # old/new в журнале описывает ровно то, что сделала эта запись.
            # Пока файл не опубликован, выдача нового содержимого невозможна:
            # запись хранит хэш нового файла, а на диске ещё прежний — сверка
            # содержимого с записью закрывает это окно отказом.
            outcome = await self._registry.record(
                name,
                origin=ORIGIN_UI,
                uploaded_by=user,
                size=len(content),
                sha256=hashlib.sha256(content).hexdigest(),
                download_allowed=download_allowed,
            )
            os.replace(staged, target)
        except Exception:
            staged.unlink(missing_ok=True)
            raise
        if not index:
            self._invalidate()
            return _upload_result(
                {
                    "registered": name,
                    "indexed": False,
                    "files": 0,
                    "chunks": 0,
                    "skipped": [],
                    "elapsed_sec": 0.0,
                },
                outcome,
            )
        try:
            report = await self._rebuild()
        except (ValueError, FileNotFoundError) as exc:
            # Документ не прошёл индексацию — не оставляем его ни файлом,
            # ни записью в реестре, иначе он будет висеть «новым» навсегда.
            target.unlink(missing_ok=True)
            await self._registry.forget(name)
            raise InvalidRequest(f"Не удалось проиндексировать: {exc}") from exc
        self._invalidate()
        return _upload_result(
            _report_payload(report, registered=name, indexed=True), outcome
        )

    async def delete(self, name: str) -> None:
        if self._registry is None:
            raise InvalidRequest(_NO_REGISTRY)
        docs_dir = Path(self.cfg.docs_dir)
        # Удаляем только документы корпуса: файл, положенный в каталог мимо
        # интерфейса, в базе знаний не участвует, и трогать его мы не вправе.
        if name not in await self._rows():
            raise NotFound(f"Документа «{name}» нет в корпусе")
        target = _document_file(docs_dir, name)
        # Файла может уже не быть (его убрали мимо интерфейса) — тогда
        # удаление просто приводит реестр и индекс в порядок.
        target.unlink(missing_ok=True)
        # Документ уходит из реестра первым: индекс пересобирается по тому,
        # что в нём осталось, и удалённый файл в корпус уже не вернётся.
        await self._registry.forget(loaders.relative_name(target, docs_dir))
        remaining = frozenset(await self._registry.names())
        await asyncio.to_thread(self._index.reindex_after_delete, str(target), remaining)
        self._invalidate()

    # ------------------------------------------------------------- служебное

    async def _rebuild(self):
        names = frozenset(await self._registry.names()) if self._registry else frozenset()
        # Индексация синхронная и тяжёлая: уводим её с цикла событий, иначе
        # на время сборки перестают отвечать все остальные запросы.
        return await asyncio.to_thread(self._index.rebuild, names)


def _report_payload(report: Any, **extra: Any) -> dict[str, Any]:
    return {
        "files": report.files,
        "chunks": report.chunks,
        "skipped": report.skipped,
        "elapsed_sec": round(report.elapsed, 1),
        **extra,
    }


def _upload_result(payload: dict[str, Any], outcome: RecordOutcome) -> UploadResult:
    """Собирает итог загрузки: ответ наружу и сведения для журнала."""
    return UploadResult(
        payload=payload,
        document_id=outcome.document.document_id,
        created=outcome.created,
        previous_download_allowed=outcome.previous_download_allowed,
        download_allowed=outcome.document.download_allowed,
    )


def _document_file(docs_dir: Path, name: str) -> Path:
    """Путь документа корпуса без выхода за каталог (имя приходит из реестра)."""
    try:
        return loaders.document_path(docs_dir, name)
    except Exception:
        return docs_dir / name


def _registry_fields(registry: dict[str, CorpusDocument], name: str) -> dict[str, Any]:
    doc = registry.get(name)
    if doc is None:
        return {
            "document_id": None,
            "download_allowed": False,
            "origin": None,
            "uploaded_by": "",
            "uploaded_at": "",
        }
    return {
        "document_id": doc.document_id,
        "download_allowed": doc.download_allowed,
        "origin": doc.origin,
        "uploaded_by": doc.uploaded_by,
        "uploaded_at": doc.uploaded_at,
    }


def _file_state(
    path: Path,
    row: dict[str, Any],
    entry: dict[str, Any] | None,
    built_at: datetime | None,
    *,
    exists: bool,
    has_index: bool,
) -> str | None:
    """Состояние документа: файл на диске и запись в индексе вместе."""
    if not exists:
        # Запись в реестре есть, файла нет: его удалили мимо интерфейса.
        return "missing"
    if not has_index:
        return None
    if entry is None:
        return "new"
    return _document_state(path, row, entry, built_at)


def _file_row(path: Path, name: str, document: CorpusDocument) -> dict[str, Any]:
    stat = path.stat()
    return {
        "name": name,
        "size": stat.st_size,
        "mtime": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
        "sha256": document.sha256,
    }


def _missing_row(name: str, document: CorpusDocument) -> dict[str, Any]:
    """Строка документа, файла которого нет: показываем то, что знает реестр."""
    return {
        "name": name,
        "size": document.size,
        "mtime": document.uploaded_at,
        "sha256": document.sha256,
    }


def _parse_ts(raw: Any) -> datetime | None:
    if not isinstance(raw, str) or not raw:
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def _document_state(
    path: Path, row: dict[str, Any], entry: dict[str, Any], built_at: datetime | None
) -> str:
    """Состояние файла относительно индекса.

    Сверяемся с фактами о самом документе (размер, дата, хэш), а не со
    временем сборки индекса: иначе правка одного файла делала бы «изменёнными»
    все остальные. Хэш читаем только тогда, когда дата файла не помогает —
    файл подменили, сохранив прежнее время.
    """
    indexed_hash = entry.get("sha256")
    indexed_mtime = _parse_ts(entry.get("mtime"))
    if not indexed_hash or indexed_mtime is None:
        # Индекс собран до появления фактов — работаем по прежнему признаку.
        if built_at is None:
            return "unknown"
        mtime = _parse_ts(row["mtime"])
        return "stale" if mtime is not None and mtime > built_at else "indexed"
    if entry.get("size") != row["size"]:
        return "stale"
    mtime = _parse_ts(row["mtime"])
    if mtime is None or mtime > indexed_mtime:
        return "stale"
    if mtime < indexed_mtime and _file_sha256(path) not in (None, indexed_hash):
        return "stale"
    return "indexed"


def _file_sha256(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        # Файл не читается — это отдельная проблема, и «изменён» здесь
        # вводило бы в заблуждение: содержимое просто не удалось проверить.
        return None
