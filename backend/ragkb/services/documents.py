"""Состояние корпуса документов и операции над ним (загрузка/удаление)."""
from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ragkb.core import loaders
from ragkb.core.config import Settings
from ragkb.core.errors import EngineUnavailable, InvalidRequest, NotFound, PayloadTooLarge
from ragkb.core.ports import IndexEngine

MAX_UPLOAD_BYTES = 20 * 1024 * 1024

_HIDDEN_PREFIXES = (".", "~$")


class DocumentsService:
    def __init__(
        self,
        cfg: Settings,
        index: IndexEngine,
        invalidate: Callable[[], None],
    ):
        self.cfg = cfg
        self._index = index
        self._invalidate = invalidate

    def list_documents(self) -> dict[str, Any]:
        docs_dir = Path(self.cfg.docs_dir)
        files = loaders.discover(docs_dir)
        try:
            manifest = self._index.manifest()
        except EngineUnavailable:
            return self._no_index_view(files)
        return self._view_with_index(files, manifest)

    def _no_index_view(self, files: list[Path]) -> dict[str, Any]:
        return {
            "docs_dir": str(Path(self.cfg.docs_dir)),
            "index": "no_index",
            "built_at": None,
            "corpus": [
                {**_file_row(f), "indexed": False, "chunks": 0, "state": None}
                for f in files
            ],
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
            corpus.append(
                {**row, "indexed": True, "chunks": entry.get("chunks", 0), "state": state}
            )

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
            report = self._index.rebuild()
        except (ValueError, FileNotFoundError) as exc:
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
        self._index.reindex_after_delete(str(target))
        self._invalidate()


def _file_row(path: Path) -> dict[str, Any]:
    stat = path.stat()
    return {
        "name": path.name,
        "size": stat.st_size,
        "mtime": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
    }
