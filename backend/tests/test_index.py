"""Индекс: дешёвые сведения о нём, манифест и одиночная пересборка.

Функциональные тесты этого не видят, а именно от этого зависит, сколько стоит
открыть страницу документов и /health: сведения о манифесте читаются с диска
и не поднимают ни эмбеддер, ни хранилище.
"""
from __future__ import annotations

import asyncio
import json
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from helpers import MemoryRegistry, corpus_names, make_app

from ragkb.core import manifest
from ragkb.core.config import Settings
from ragkb.core.errors import Conflict, EngineUnavailable
from ragkb.core.index import ConfigIndex
from ragkb.core.pipeline import build_index
from ragkb.services.documents import DocumentsService
from ragkb.services.index import IndexService


def _cfg(tmp_path: Path) -> Settings:
    docs = tmp_path / "docs"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "policy.md").write_text(
        "# Политика\n\n## Отпуск\n\nЕжегодный отпуск: 28 календарных дней.\n",
        encoding="utf-8",
    )
    cfg = Settings(docs_dir=str(docs), index_dir=str(tmp_path / "index"))
    cfg.store.backend = "memory"
    cfg.embedding.backend = "fake"
    cfg.logging.dir = str(tmp_path / "logs")
    return cfg


def _forbidden_engine():
    """Движок, который строить нельзя: модель эмбеддингов здесь не нужна."""

    def build():
        raise AssertionError("движок собран, хотя для этих сведений он не нужен")

    return build


# ------------------------------------------------- сведения без сборки движка


async def test_document_listing_does_not_build_engine(tmp_path):
    cfg = _cfg(tmp_path)
    registry = MemoryRegistry().add(cfg)
    build_index(cfg, registry.index_names())
    svc = DocumentsService(
        cfg, ConfigIndex(cfg, _forbidden_engine()), lambda: None, registry
    )

    body = await svc.list_documents()

    assert body["index"] == "ok"
    assert [r["state"] for r in body["corpus"]] == ["indexed"]


def test_status_does_not_build_engine(tmp_path):
    cfg = _cfg(tmp_path)
    build_index(cfg, corpus_names(cfg))

    status = IndexService(ConfigIndex(cfg, _forbidden_engine()), lambda: None).status()

    assert status["status"] == "ok"
    assert status["documents"] == 1
    assert status["chunks"] >= 1


def test_probe_reports_missing_index_without_engine(tmp_path):
    cfg = _cfg(tmp_path)
    index = ConfigIndex(cfg, _forbidden_engine())

    assert index.probe() == "no_index"
    with pytest.raises(EngineUnavailable):
        index.manifest()

    build_index(cfg, corpus_names(cfg))
    assert index.probe() == "ok"


def test_health_does_not_build_engine(tmp_path, monkeypatch):
    """docker healthcheck стучит в /health каждые 30 секунд."""

    def boom(*_args, **_kwargs):
        raise AssertionError("движок собран на проверке живости")

    cfg = _cfg(tmp_path)
    build_index(cfg, corpus_names(cfg))
    monkeypatch.setattr("ragkb.core.engine.RagChain", boom)
    with TestClient(make_app(cfg)) as client:
        assert client.get("/health").json() == {"status": "ok"}


def test_health_reports_missing_index(tmp_path, monkeypatch):
    def boom(*_args, **_kwargs):
        raise AssertionError("движок собран на проверке живости")

    cfg = _cfg(tmp_path)
    monkeypatch.setattr("ragkb.core.engine.RagChain", boom)
    with TestClient(make_app(cfg)) as client:
        assert client.get("/health").json() == {"status": "no_index"}


# ------------------------------------------------------------------- манифест


def test_manifest_records_what_index_was_built_with(tmp_path):
    cfg = _cfg(tmp_path)

    build_index(cfg, corpus_names(cfg))

    indexed = manifest.read(cfg)
    assert indexed["store"] == "memory"
    assert indexed["embedder"] == "fake:1024"
    assert indexed["dim"] == 1024
    assert indexed["built_at"]
    assert indexed["n_chunks"] >= 1


def test_broken_manifest_is_reported(tmp_path):
    cfg = _cfg(tmp_path)
    build_index(cfg, corpus_names(cfg))
    (Path(cfg.index_dir) / "manifest.json").write_text("{не json", encoding="utf-8")

    with pytest.raises(EngineUnavailable) as exc:
        manifest.read(cfg)
    assert "повреждён" in exc.value.detail


def test_manifest_documents_keep_file_facts(tmp_path):
    cfg = _cfg(tmp_path)

    build_index(cfg, corpus_names(cfg))

    document = manifest.read(cfg)["documents"][0]
    assert document["source"].endswith("policy.md")
    assert document["sha256"]
    assert document["size"] > 0


# ------------------------------------------------- одиночная пересборка


def test_rebuild_is_single_flight(tmp_path, monkeypatch):
    """Вторая пересборка не запускается поверх первой, а получает отказ."""
    cfg = _cfg(tmp_path)
    started = threading.Event()

    def slow_build(*_args, **_kwargs):
        started.set()
        time.sleep(0.4)
        return SimpleNamespace(
            files=1, chunks=1, skipped=[], excluded=[], elapsed=0.0, embedder="fake:1024"
        )

    monkeypatch.setattr("ragkb.core.index.build_index", slow_build)
    index = ConfigIndex(cfg, _forbidden_engine())
    names = corpus_names(cfg)
    results: list[object] = []

    def worker() -> None:
        try:
            results.append(index.rebuild(names))
        except Conflict as exc:
            results.append(exc)

    first = threading.Thread(target=worker)
    first.start()
    assert started.wait(timeout=5), "первая пересборка не началась"
    second = threading.Thread(target=worker)
    second.start()
    first.join(timeout=5)
    second.join(timeout=5)

    assert any(isinstance(r, Conflict) for r in results), results
    assert any(not isinstance(r, Conflict) for r in results), results


def test_rebuild_lock_is_released_after_failure(tmp_path, monkeypatch):
    """Упавшая пересборка не должна блокировать следующие попытки."""
    cfg = _cfg(tmp_path)

    def failing(*_args, **_kwargs):
        raise ValueError("нет документов")

    monkeypatch.setattr("ragkb.core.index.build_index", failing)
    index = ConfigIndex(cfg, _forbidden_engine())
    for _ in range(2):
        with pytest.raises(ValueError):
            index.rebuild(corpus_names(cfg))


def test_rebuild_reports_unavailable_ollama(tmp_path):
    """Администратор должен увидеть причину, а не «внутреннюю ошибку»."""
    cfg = _cfg(tmp_path)
    registry = MemoryRegistry().add(cfg)
    cfg.embedding.backend = "ollama"
    cfg.embedding.base_url = "http://127.0.0.1:1"
    service = IndexService(
        ConfigIndex(cfg, _forbidden_engine()), lambda: None, registry=registry
    )

    with pytest.raises(EngineUnavailable) as exc:
        asyncio.run(service.rebuild())

    assert "Ollama недоступна" in exc.value.detail


def test_rebuild_after_delete_drops_manifest_when_corpus_is_empty(tmp_path):
    """Удаление последнего документа убирает индекс целиком."""
    cfg = _cfg(tmp_path)
    build_index(cfg, corpus_names(cfg))
    target = Path(cfg.docs_dir) / "policy.md"
    index = ConfigIndex(cfg, _forbidden_engine())

    target.unlink()
    index.reindex_after_delete(str(target), frozenset())

    assert not Path(cfg.index_dir).exists()
    assert manifest.exists(cfg) is False


def test_rebuild_after_delete_removes_chunks_of_one_document(tmp_path):
    cfg = _cfg(tmp_path)
    (Path(cfg.docs_dir) / "second.md").write_text("# Второй\n\nТекст.\n", encoding="utf-8")
    build_index(cfg, corpus_names(cfg))
    target = Path(cfg.docs_dir) / "second.md"
    index = ConfigIndex(cfg, _forbidden_engine())

    target.unlink()
    index.reindex_after_delete(str(target), frozenset({"policy.md"}))

    indexed = manifest.read(cfg)
    assert [Path(d["source"]).name for d in indexed["documents"]] == ["policy.md"]
    assert json.dumps(indexed["documents"], ensure_ascii=False)
