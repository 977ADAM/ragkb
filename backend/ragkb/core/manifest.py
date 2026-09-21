"""Манифест индекса: чем собран, что вошло и когда.

Chroma хранит чанки и метаданные, но не отвечает на вопросы «собран ли индекс
вообще», «какой моделью» и «какие файлы изменились после сборки». Это нужно
`/health`, `/api/v1/status` и странице документов, поэтому рядом с индексом
лежит небольшой JSON.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import Settings
from .errors import EngineUnavailable

MANIFEST = "manifest.json"
_DOCUMENT_FACTS = ("mtime", "size", "sha256")


def manifest_path(cfg: Settings) -> Path:
    return Path(cfg.index_dir) / MANIFEST


def exists(cfg: Settings) -> bool:
    return manifest_path(cfg).exists()


def read(cfg: Settings) -> dict[str, Any]:
    path = manifest_path(cfg)
    if not path.exists():
        raise EngineUnavailable(f"Индекс не найден в {cfg.index_dir}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise EngineUnavailable(f"Манифест индекса повреждён: {exc}") from exc


def write(
    cfg: Settings,
    *,
    store_backend: str,
    embedder: str,
    dim: int,
    chunks: int,
    documents: list[dict[str, Any]],
    skipped: list[tuple[str, str]] | None = None,
) -> dict[str, Any]:
    """Пишет манифест и возвращает его содержимое."""
    payload: dict[str, Any] = {
        "store": store_backend,
        "embedder": embedder,
        "dim": dim,
        "n_chunks": chunks,
        "built_at": datetime.now(timezone.utc).isoformat(),
        "chunk_size": cfg.chunking.size,
        "chunk_overlap": cfg.chunking.overlap,
        "documents": documents,
        "skipped": [list(item) for item in (skipped or [])],
    }
    path = manifest_path(cfg)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def remove(cfg: Settings) -> None:
    path = manifest_path(cfg)
    if path.exists():
        path.unlink()


def file_facts(path: str | Path, checksum: str) -> dict[str, Any]:
    """Факты о файле для манифеста.

    Хэш содержимого и размер отвечают на вопрос «тот ли это документ», а
    mtime — «менялся ли он после индексации». Вместе они надёжнее, чем
    сравнение со временем сборки индекса: переиндексация соседнего файла
    не делает вид, что изменились все.
    """
    stat = Path(path).stat()
    return {
        "mtime": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
        "size": stat.st_size,
        "sha256": checksum,
    }


def documents_summary(
    chunks: list[Any], facts: dict[str, dict[str, Any]] | None = None
) -> list[dict[str, Any]]:
    """Записи о документах для манифеста: заголовок, путь, число чанков, факты."""
    seen: dict[str, dict[str, Any]] = {}
    for chunk in chunks:
        metadata = chunk.metadata
        doc_id = str(metadata.get("doc_id") or "")
        entry = seen.setdefault(
            doc_id,
            {
                "title": str(metadata.get("title") or ""),
                "source": str(metadata.get("source") or ""),
                "chunks": 0,
            },
        )
        entry["chunks"] += 1
    for entry in seen.values():
        entry.update((facts or {}).get(entry["source"], {}))
    return list(seen.values())


def merged_documents(
    chunks: list[Any], previous: list[dict[str, Any]] | None = None
) -> list[dict[str, Any]]:
    """Сводка о документах с сохранением уже известных фактов о файлах.

    При инкрементальном обновлении факты берём из прежнего манифеста: чанки
    их не знают, а страница документов без них не отличит свежий файл от
    подменённого.
    """
    facts = {
        str(entry.get("source") or ""): {
            key: entry[key] for key in _DOCUMENT_FACTS if key in entry
        }
        for entry in (previous or [])
    }
    return documents_summary(chunks, facts)
