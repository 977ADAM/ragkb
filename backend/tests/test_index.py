"""Индекс: дешёвые сведения о нём, кеш эмбеддера и одиночная пересборка.

Функциональные тесты этого не видят, а именно от этого зависит, сколько стоит
открыть страницу документов: раньше любое обращение к манифесту поднимало
модель эмбеддингов (гигабайты памяти, десятки секунд на CPU).
"""
from __future__ import annotations

import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from helpers import make_app

from ragkb.core.config import Settings
from ragkb.core.embeddings import build_embedder
from ragkb.core.errors import Conflict, EngineUnavailable
from ragkb.core.index import ConfigIndex
from ragkb.core.pipeline import build_index
from ragkb.services.documents import DocumentsService
from ragkb.services.index import IndexService


def _cfg(tmp_path: Path) -> Settings:
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "policy.md").write_text(
        "# Политика\n\n## Отпуск\n\nЕжегодный отпуск: 28 календарных дней.\n",
        encoding="utf-8",
    )
    cfg = Settings(docs_dir=str(docs), index_dir=str(tmp_path / "index"))
    cfg.store.backend = "numpy"
    return cfg


def _forbidden_engine():
    """Движок, который строить нельзя: модель эмбеддингов здесь не нужна."""

    def build():
        raise AssertionError("движок собран, хотя для этих сведений он не нужен")

    return build


# ------------------------------------------------- сведения без сборки движка


async def test_document_listing_does_not_build_engine(tmp_path):
    cfg = _cfg(tmp_path)
    build_index(cfg)
    svc = DocumentsService(cfg, ConfigIndex(cfg, _forbidden_engine()), lambda: None)
    body = await svc.list_documents()
    assert body["index"] == "ok"
    assert [r["state"] for r in body["corpus"]] == ["indexed"]


def test_status_does_not_build_engine(tmp_path):
    cfg = _cfg(tmp_path)
    build_index(cfg)
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

    build_index(cfg)
    assert index.probe() == "ok"


def test_health_does_not_build_engine(tmp_path, monkeypatch):
    """docker healthcheck стучит в /health каждые 30 секунд."""

    def boom(*_args, **_kwargs):
        raise AssertionError("движок собран на проверке живости")

    cfg = _cfg(tmp_path)
    cfg.history.enabled = False  # без истории БД не нужна
    build_index(cfg)
    monkeypatch.setattr("ragkb.core.engine.RAGPipeline", boom)
    with TestClient(make_app(cfg)) as client:
        assert client.get("/health").json() == {"status": "ok"}


def test_health_reports_missing_index(tmp_path, monkeypatch):
    def boom(*_args, **_kwargs):
        raise AssertionError("движок собран на проверке живости")

    cfg = _cfg(tmp_path)
    cfg.history.enabled = False
    monkeypatch.setattr("ragkb.core.engine.RAGPipeline", boom)
    with TestClient(make_app(cfg)) as client:
        assert client.get("/health").json() == {"status": "no_index"}


# ----------------------------------------------------------- кеш эмбеддера


def test_embedder_is_reused_for_same_config():
    """Пересборка индекса не должна поднимать модель заново."""
    cfg = Settings.EmbeddingConfig()
    cfg.backend = "tfidf"
    first = build_embedder(cfg)
    assert build_embedder(cfg) is first


def test_embedder_differs_for_other_config():
    first = Settings.EmbeddingConfig()
    first.backend = "tfidf"
    other = Settings.EmbeddingConfig()
    other.backend = "tfidf"
    other.tfidf_dim = 128
    assert build_embedder(first) is not build_embedder(other)


# ------------------------------------------------- одиночная пересборка


def test_rebuild_is_single_flight(tmp_path, monkeypatch):
    """Вторая пересборка не запускается поверх первой, а получает отказ."""
    cfg = _cfg(tmp_path)
    started = threading.Event()

    def slow_build(*_args, **_kwargs):
        started.set()
        time.sleep(0.4)
        return SimpleNamespace(
            files=1, chunks=1, skipped=[], excluded=[], elapsed=0.0, embedder="tfidf"
        )

    monkeypatch.setattr("ragkb.core.index.build_index", slow_build)
    index = ConfigIndex(cfg, _forbidden_engine())
    results: list[object] = []

    def worker() -> None:
        try:
            results.append(index.rebuild())
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
            index.rebuild()
