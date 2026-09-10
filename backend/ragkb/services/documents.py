"""Корпус документов: реестр, состояние и операции над файлами.

Реестр (таблица `corpus_documents`) — источник истины о том, что принадлежит
базе знаний. Индекс собирается только по нему, поэтому файл, положенный в
каталог мимо интерфейса, в ответы не попадёт, пока администратор не примет
его на странице документов. Без реестра (нет БД) сервис работает по-прежнему:
индексируется всё, что лежит в каталоге, — так остаётся рабочим режим
`auth.mode: disabled` без Postgres.
"""
from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ragkb.core import loaders
from ragkb.core.config import Settings
from ragkb.core.errors import EngineUnavailable, InvalidRequest, NotFound, PayloadTooLarge
from ragkb.core.ports import IndexEngine
from ragkb.domain.entities import ORIGIN_EXTERNAL, ORIGIN_UI, CorpusDocument
from ragkb.domain.ports import DocumentRegistry

MAX_UPLOAD_BYTES = 20 * 1024 * 1024

_HIDDEN_PREFIXES = (".", "~$")


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
        files = loaders.discover(docs_dir)
        registry = await self._rows()
        try:
            manifest = self._index.manifest()
        except EngineUnavailable:
            return self._view(files, docs_dir, registry, manifest=None)
        return self._view(files, docs_dir, registry, manifest=manifest)

    async def _rows(self) -> dict[str, CorpusDocument] | None:
        if self._registry is None:
            return None
        return {doc.name: doc for doc in await self._registry.list_all()}

    def _view(
        self,
        files: list[Path],
        docs_dir: Path,
        registry: dict[str, CorpusDocument] | None,
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
        external = 0
        for path in files:
            name = loaders.relative_name(path, docs_dir)
            row = _file_row(path, name)
            entry = by_source.get(str(path)) or by_name.get(path.name)
            registered = registry is None or name in registry
            if not registered:
                external += 1
            if entry is not None:
                indexed_docs += 1
                total_chunks += int(entry.get("chunks", 0))
            corpus.append(
                {
                    **row,
                    **_registry_fields(registry, name),
                    "registered": registered,
                    "indexed": entry is not None,
                    "chunks": entry.get("chunks", 0) if entry else 0,
                    "state": _file_state(
                        path,
                        row,
                        entry,
                        built_at,
                        registered=registered,
                        has_index=manifest is not None,
                    ),
                }
            )

        file_paths = {str(f) for f in files}
        names = {f.name for f in files}
        orphans = [
            {k: d.get(k) for k in ("title", "source", "chunks")}
            for d in documents
            if d["source"] not in file_paths and Path(d["source"]).name not in names
        ]
        return {
            "docs_dir": str(docs_dir),
            "index": "ok" if manifest is not None else "no_index",
            "registry": "on" if registry is not None else "off",
            "built_at": built_at_raw,
            "corpus": corpus,
            "orphans": orphans,
            "skipped": list((manifest or {}).get("skipped", [])),
            "summary": {
                "corpus_files": len(files),
                "indexed_docs": indexed_docs,
                "chunks": total_chunks,
                "external_files": external,
            },
        }

    # -------------------------------------------------------------- операции

    async def upload(
        self, filename: str, content: bytes, user: str = "", *, index: bool = True
    ) -> dict[str, Any]:
        """Сохраняет документ и заводит его в реестре.

        `index=False` — файл только принимается: так грузится пачка, и одну
        индексацию делают в конце, а не после каждого файла.
        """
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
        if self._registry is not None:
            await self._registry.record(
                name,
                origin=ORIGIN_UI,
                uploaded_by=user,
                size=len(content),
                sha256=hashlib.sha256(content).hexdigest(),
            )
        if not index:
            self._invalidate()
            return {
                "registered": name,
                "indexed": False,
                "files": 0,
                "chunks": 0,
                "skipped": [],
                "excluded": [],
                "elapsed_sec": 0.0,
            }
        try:
            report = await self._rebuild()
        except (ValueError, FileNotFoundError) as exc:
            # Документ не прошёл индексацию — не оставляем его ни файлом,
            # ни записью в реестре, иначе он будет висеть «новым» навсегда.
            target.unlink(missing_ok=True)
            if self._registry is not None:
                await self._registry.forget(name)
            raise InvalidRequest(f"Не удалось проиндексировать: {exc}") from exc
        self._invalidate()
        return _report_payload(report, registered=name, indexed=True)

    async def accept(self, names: list[str], user: str = "") -> dict[str, Any]:
        """Принимает в корпус файлы, положенные в каталог мимо интерфейса."""
        if self._registry is None:
            raise InvalidRequest(
                "Реестр документов недоступен: без него индексируется весь "
                "каталог, принимать отдельные файлы не нужно."
            )
        if not names:
            raise InvalidRequest("Не указан ни один документ")
        docs_dir = Path(self.cfg.docs_dir)
        accepted: list[str] = []
        for raw in names:
            name = loaders.relative_name(raw, docs_dir) if Path(raw).is_absolute() else raw
            target = _safe_target(docs_dir, name)
            if not target.is_file():
                raise NotFound(f"Файл «{name}» не найден в каталоге документов")
            await self._registry.record(
                name,
                origin=ORIGIN_EXTERNAL,
                uploaded_by=user,
                size=target.stat().st_size,
                sha256=hashlib.sha256(target.read_bytes()).hexdigest(),
            )
            accepted.append(name)
        try:
            report = await self._rebuild()
        except (ValueError, FileNotFoundError) as exc:
            raise InvalidRequest(f"Не удалось проиндексировать: {exc}") from exc
        self._invalidate()
        return {**_report_payload(report), "accepted": accepted}

    async def delete(self, name: str) -> None:
        docs_dir = Path(self.cfg.docs_dir)
        target = _safe_target(docs_dir, name)
        if not target.is_file():
            raise NotFound(f"Файл «{name}» не найден в каталоге документов")
        target.unlink()
        key = loaders.relative_name(target, docs_dir)
        if self._registry is not None:
            await self._registry.forget(key)
        allow = await self._allowed_names()
        await asyncio.to_thread(self._index.reindex_after_delete, str(target), allow)
        self._invalidate()

    # ------------------------------------------------------------- служебное

    async def _allowed_names(self) -> frozenset[str] | None:
        """Имена принятых документов; None — реестра нет, индексируем всё."""
        if self._registry is None:
            return None
        return frozenset(await self._registry.names())

    async def _rebuild(self):
        allow = await self._allowed_names()
        # Индексация синхронная и тяжёлая: уводим её с цикла событий, иначе
        # на время сборки перестают отвечать все остальные запросы.
        return await asyncio.to_thread(self._index.rebuild, allow)


def _report_payload(report: Any, **extra: Any) -> dict[str, Any]:
    return {
        "files": report.files,
        "chunks": report.chunks,
        "skipped": report.skipped,
        "excluded": report.excluded,
        "elapsed_sec": round(report.elapsed, 1),
        **extra,
    }


def _safe_target(docs_dir: Path, name: str) -> Path:
    """Путь файла внутри каталога корпуса. Выход за каталог запрещён."""
    if not name or name.startswith(_HIDDEN_PREFIXES):
        raise InvalidRequest("Недопустимое имя файла")
    root = docs_dir.resolve()
    candidate = (docs_dir / name).resolve()
    if candidate != root and root not in candidate.parents:
        raise InvalidRequest("Недопустимое имя файла")
    return candidate


def _registry_fields(
    registry: dict[str, CorpusDocument] | None, name: str
) -> dict[str, Any]:
    doc = (registry or {}).get(name)
    if doc is None:
        return {"origin": None, "uploaded_by": "", "uploaded_at": ""}
    return {
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
    registered: bool,
    has_index: bool,
) -> str | None:
    """Состояние документа: реестр, файл и запись в индексе вместе."""
    if not registered:
        # Файл лежит мимо интерфейса: в индекс он не попадёт, пока его не примут.
        return "external"
    if not has_index:
        return None
    if entry is None:
        return "new"
    return _document_state(path, row, entry, built_at)


def _file_row(path: Path, name: str) -> dict[str, Any]:
    stat = path.stat()
    return {
        "name": name,
        "size": stat.st_size,
        "mtime": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
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
