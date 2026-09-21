"""Эмбеддинги Ollama: пакеты, размерность, повторы и понятные отказы.

Сеть не нужна: httpx.MockTransport подменяет транспорт, поэтому проверяются
и разбор ответов Ollama, и текст ошибок, который увидит администратор.
"""
from __future__ import annotations

import json
from typing import Any

import httpx
import numpy as np
import pytest

from ragkb.core.config import Settings
from ragkb.core.embeddings import OllamaEmbedder
from ragkb.core.errors import EngineUnavailable

DIM = 4


class FakeOllama:
    """Мини-сервер Ollama: /api/show, /api/embed, /api/tags."""

    def __init__(
        self,
        *,
        dim: int = DIM,
        capabilities: tuple[str, ...] = ("embedding",),
        model: str = "qwen3-embedding:0.6b",
        installed: list[str] | None = None,
        status: int = 200,
    ):
        self.dim = dim
        self.capabilities = list(capabilities)
        self.model = model
        self.installed = installed if installed is not None else [model]
        self.status = status
        # Сколько первых запросов эмбеддингов отдать пятисоткой.
        self.fail_times = 0
        # Вернуть меньше векторов, чем пришло текстов: так ведёт себя модель
        # без поддержки пакетного ввода.
        self.mismatch = False
        self.requests: list[tuple[str, dict[str, Any]]] = []

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    def handle(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else {}
        self.requests.append((request.url.path, body))
        if request.url.path == "/api/embed":
            if self.fail_times > 0:
                self.fail_times -= 1
                return httpx.Response(500, json={"error": "server busy"})
            texts = body.get("input") or []
            count = max(1, len(texts) - 1) if self.mismatch else len(texts)
            return httpx.Response(
                200,
                json={"embeddings": [self._vector(text) for text in texts[:count]]},
            )
        if request.url.path == "/api/show":
            if self.status != 200:
                return httpx.Response(
                    self.status, json={"error": f'model "{body.get("model")}" not found'}
                )
            return httpx.Response(
                200,
                json={
                    "capabilities": self.capabilities,
                    "model_info": {
                        "general.architecture": "qwen3",
                        "qwen3.embedding_length": self.dim,
                    },
                },
            )
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": n} for n in self.installed]})
        return httpx.Response(404, json={"error": "unknown endpoint"})

    def _vector(self, text: str) -> list[float]:
        """Вектор зависит только от текста; нормализация порядок не сбивает.

        Первая координата растёт с длиной текста: если эмбеддер склеит пакеты
        не в том порядке, длины в выдаче пойдут не по возрастанию.
        """
        vector = [0.0] * self.dim
        vector[0] = float(len(text))
        vector[1] = 1.0
        return vector

    def payloads(self, path: str) -> list[dict[str, Any]]:
        return [body for url, body in self.requests if url == path]


def _embedder(transport: httpx.MockTransport, **overrides: Any) -> OllamaEmbedder:
    cfg = Settings.EmbeddingConfig()
    cfg.backend = "ollama"
    cfg.model = "qwen3-embedding:0.6b"
    cfg.base_url = "http://ollama.test:11434"
    cfg.batch_size = 2
    cfg.retries = 1
    for key, value in overrides.items():
        setattr(cfg, key, value)
    return OllamaEmbedder(cfg, transport=transport)


# ------------------------------------------------------------------ векторы


def test_documents_are_batched_and_order_is_kept():
    fake = FakeOllama(dim=4)
    matrix = _embedder(fake.transport()).embed_documents(["x", "xx", "xxx", "xxxx", "xxxxx"])

    assert matrix.shape == (5, 4)
    assert np.allclose(np.linalg.norm(matrix, axis=1), 1.0, atol=1e-6)
    # batch_size=2 → 2 + 2 + 1 текста, и порядок векторов исходный.
    assert [len(p["input"]) for p in fake.payloads("/api/embed")] == [2, 2, 1]
    lengths = matrix[:, 0].tolist()
    assert lengths == sorted(lengths)


def test_payload_keeps_model_loaded():
    fake = FakeOllama()
    _embedder(fake.transport(), keep_alive="42m").embed_documents(["текст"])

    payload = fake.payloads("/api/embed")[0]
    assert payload["model"] == "qwen3-embedding:0.6b"
    assert payload["truncate"] is True
    assert payload["keep_alive"] == "42m"


def test_prefixes_reach_ollama():
    fake = FakeOllama()
    embedder = _embedder(
        fake.transport(), doc_prefix="search_document: ", query_prefix="search_query: "
    )
    embedder.embed_documents(["документ"])
    embedder.embed_query("вопрос")

    assert fake.payloads("/api/embed")[0]["input"] == ["search_document: документ"]
    assert fake.payloads("/api/embed")[1]["input"] == ["search_query: вопрос"]


def test_dim_comes_from_show_without_counting_vectors():
    """ /api/show дешевле эмбеддинга: метаданные модели вместо пробы."""
    fake = FakeOllama(dim=1024)
    embedder = _embedder(fake.transport())

    assert embedder.dim == 1024
    assert fake.payloads("/api/embed") == []


def test_batch_mismatch_is_rejected():
    fake = FakeOllama()
    fake.mismatch = True
    with pytest.raises(EngineUnavailable) as exc:
        _embedder(fake.transport()).embed_documents(["a", "b", "c"])
    assert "пакетный запрос отклонён" in exc.value.detail


def test_empty_input_needs_no_request():
    fake = FakeOllama()
    matrix = _embedder(fake.transport()).embed_documents([])
    assert matrix.shape == (0, 0)
    assert fake.requests == []


# ------------------------------------------------------------------ проверки


def test_check_accepts_embedding_model():
    fake = FakeOllama(dim=768)
    _embedder(fake.transport()).check()
    assert fake.payloads("/api/show")


def test_check_rejects_chat_model():
    """Чат-модель вместо модели эмбеддингов — частая ошибка в конфиге."""
    fake = FakeOllama(capabilities=("completion", "tools"))
    with pytest.raises(EngineUnavailable) as exc:
        _embedder(fake.transport()).check()
    assert "не считает эмбеддинги" in exc.value.detail
    assert "qwen3-embedding" in exc.value.detail


def test_missing_model_tells_how_to_pull_it():
    fake = FakeOllama(status=404, installed=["qwen3:4b", "qwen2.5:14b-instruct"])
    with pytest.raises(EngineUnavailable) as exc:
        _embedder(fake.transport()).check()
    detail = exc.value.detail
    assert "ollama pull qwen3-embedding:0.6b" in detail
    assert "qwen3:4b" in detail


def test_unreachable_ollama_is_explained():
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    with pytest.raises(EngineUnavailable) as exc:
        _embedder(httpx.MockTransport(boom)).check()
    assert "Ollama недоступна" in exc.value.detail
    assert "ollama serve" in exc.value.detail


def test_blank_address_is_rejected_early():
    cfg = Settings.EmbeddingConfig()
    cfg.backend = "ollama"
    cfg.base_url = ""
    with pytest.raises(EngineUnavailable) as exc:
        OllamaEmbedder(cfg)
    assert "RAGKB_EMBEDDING_URL" in exc.value.detail


def test_transient_failure_is_retried(monkeypatch):
    fake = FakeOllama()
    fake.fail_times = 1
    pauses: list[float] = []
    monkeypatch.setattr("ragkb.core.embeddings.time.sleep", lambda seconds: pauses.append(seconds))

    matrix = _embedder(fake.transport(), retries=3).embed_documents(["текст"])

    assert matrix.shape == (1, DIM)
    assert len(fake.payloads("/api/embed")) == 2
    assert pauses, "между попытками должна быть пауза"


def test_exhausted_retries_report_status(monkeypatch):
    fake = FakeOllama()
    fake.fail_times = 5
    monkeypatch.setattr("ragkb.core.embeddings.time.sleep", lambda _seconds: None)

    with pytest.raises(EngineUnavailable) as exc:
        _embedder(fake.transport(), retries=2).embed_documents(["текст"])
    assert "500" in exc.value.detail
