"""Эмбеддинги: сборка бэкенда и перевод отказов в понятный текст.

Сети нет: проверяются конфигурация, детерминированный fake-бэкенд и
сообщения об отказах Ollama (их читает администратор в интерфейсе).
"""
from __future__ import annotations

import pytest
from langchain_core.embeddings import DeterministicFakeEmbedding

from ragkb.core.config import Settings
from ragkb.core.embeddings import (
    build_embeddings,
    embedder_name,
    embedding_dim,
    explain_embedding_error,
)
from ragkb.core.errors import EngineUnavailable


def test_default_backend_is_ollama():
    cfg = Settings.EmbeddingConfig()
    assert cfg.backend == "ollama"
    assert cfg.model == "qwen3-embedding:0.6b"
    assert cfg.base_url == "http://127.0.0.1:11434"
    assert cfg.keep_alive == "30m"


def test_environment_overrides_embedding_backend(monkeypatch):
    """Тесты и офлайн-прогоны переключают бэкенд переменной окружения."""
    monkeypatch.setenv("RAGKB_EMBEDDING_BACKEND", "fake")
    assert Settings().embedding.backend == "fake"


def test_fake_backend_is_deterministic():
    cfg = Settings.EmbeddingConfig(backend="fake", fake_dim=32)
    embeddings = build_embeddings(cfg)

    assert isinstance(embeddings, DeterministicFakeEmbedding)
    first = embeddings.embed_query("отпуск")
    second = embeddings.embed_query("отпуск")
    assert first == second
    assert len(first) == 32
    assert embedding_dim(embeddings) == 32


def test_unknown_backend_is_rejected():
    with pytest.raises(EngineUnavailable) as exc:
        build_embeddings(Settings.EmbeddingConfig(backend="tfidf"))
    assert "ollama и fake" in exc.value.detail


def test_ollama_without_address_is_rejected_early():
    with pytest.raises(EngineUnavailable) as exc:
        build_embeddings(Settings.EmbeddingConfig(backend="ollama", base_url=""))
    assert "RAGKB_EMBEDDING_URL" in exc.value.detail


def test_embedder_name_reflects_model():
    assert embedder_name(Settings.EmbeddingConfig(model="bge-m3")) == "ollama:bge-m3"
    assert embedder_name(Settings.EmbeddingConfig(backend="fake", fake_dim=64)) == "fake:64"


def test_missing_model_message_tells_how_to_pull():
    cfg = Settings.EmbeddingConfig(model="qwen3-embedding:8b")
    detail = explain_embedding_error(
        RuntimeError('model "qwen3-embedding:8b" not found, try pulling it first'), cfg
    )
    assert "ollama pull qwen3-embedding:8b" in detail


def test_unreachable_ollama_message_tells_what_to_do():
    cfg = Settings.EmbeddingConfig()
    detail = explain_embedding_error(ConnectionError("Connection refused"), cfg)
    assert "Ollama недоступна" in detail
    assert "ollama serve" in detail


def test_other_failure_keeps_reason():
    cfg = Settings.EmbeddingConfig()
    detail = explain_embedding_error(RuntimeError("502 Bad Gateway"), cfg)
    assert "502 Bad Gateway" in detail
    assert "ollama:qwen3-embedding:0.6b" in detail


@pytest.mark.integration
def test_ollama_embeddings_against_live_server():
    """Живая проверка: модель установлена и отдаёт вектор нужной длины."""
    cfg = Settings.EmbeddingConfig()
    embeddings = build_embeddings(cfg)

    vector = embeddings.embed_query("сколько дней отпуска")

    assert len(vector) == 1024
    assert len(embeddings.embed_documents(["первый", "второй"])) == 2
