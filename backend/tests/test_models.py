from ragkb.core.catalogs import embedding_models
from ragkb.core.catalogs.ollama import OllamaCatalog, embedding_options
from ragkb.core.catalogs.openai import OpenAICatalog
from ragkb.core.catalogs.static import StaticCatalog
from ragkb.core.config import Settings
from ragkb.services.models import ModelsService


def test_openai_catalog_short_name_for_gguf_path():
    cfg = Settings.LLMConfig(
        backend="openai",
        model="/home/adminai/models/qwen.gguf",
    )
    cat = OpenAICatalog(
        cfg,
        installed=[{"id": "/home/adminai/models/qwen.gguf"}],
    )
    item = cat.list()[0]
    assert item.id == "/home/adminai/models/qwen.gguf"
    assert item.display_name == "qwen.gguf"


def test_openai_catalog_filters_and_falls_back():
    cfg = Settings.LLMConfig(backend="openai", model="a", available=[{"name": "a"}])
    cat = OpenAICatalog(
        cfg,
        installed=[{"id": "a"}, {"id": "b"}],
    )
    assert {m.id for m in cat.list()} == {"a"}
    empty = OpenAICatalog(Settings.LLMConfig(backend="openai", model="local"), installed=[])
    assert empty.list()[0].id == "local"


def test_static_catalog_default():
    cat = StaticCatalog(Settings.LLMConfig(model="local-gguf"))
    assert cat.list()[0].id == "local-gguf"
    assert cat.resolve(None) == "local-gguf"


def test_ollama_catalog_filters_and_resolve():
    cfg = Settings.LLMConfig(backend="ollama", model="a", available=[{"name": "a"}])
    cat = OllamaCatalog(
        cfg,
        installed=[
            {"id": "a", "context_window": 8, "supports_tools": False},
            {"id": "b", "context_window": None, "supports_tools": True},
        ],
    )
    ids = {m.id for m in cat.list()}
    assert ids == {"a"}
    try:
        cat.resolve("b")
        raise AssertionError("ожидали ValueError")
    except ValueError:
        pass


# ------------------------------------------------- модели эмбеддингов


def test_embedding_options_keep_only_embedding_capability():
    installed = [
        {"id": "qwen3:4b", "capabilities": ["completion", "tools"], "embedding_dim": None},
        {
            "id": "qwen3-embedding:0.6b",
            "capabilities": ["embedding"],
            "embedding_dim": 1024,
            "size": 639_000_000,
        },
        {"id": "qwen2.5:7b-instruct", "capabilities": ["completion"], "embedding_dim": None},
    ]

    options = embedding_options(installed)

    assert [item["id"] for item in options] == ["qwen3-embedding:0.6b"]
    assert options[0]["dim"] == 1024
    assert "1024 координат" in options[0]["label"]


def test_embedding_options_fall_back_when_capabilities_unknown():
    """Старые сборки Ollama о возможностях не сообщают — показываем всё."""
    installed = [{"id": "nomic-embed-text", "capabilities": [], "embedding_dim": 768}]

    assert [item["id"] for item in embedding_options(installed)] == ["nomic-embed-text"]


def test_embedding_models_empty_for_test_backend():
    cfg = Settings(embedding=Settings.EmbeddingConfig(backend="fake", fake_dim=64))

    assert embedding_models(cfg) == []


def test_embedding_models_come_from_openai_server(monkeypatch):
    """У OpenAI-совместимого бэкенда список берётся из его GET /models."""
    seen: list[tuple[str, str]] = []

    def fake_listed(base_url: str, api_key: str = "") -> list[dict]:
        seen.append((base_url, api_key))
        return [{"id": "USER2-small"}]

    monkeypatch.setattr("ragkb.core.catalogs.listed_models", fake_listed)
    # Окружение сильнее явно переданной конфигурации (см. Settings._apply_env),
    # а conftest для всех тестов выставляет fake: здесь он же и нужен.
    monkeypatch.setenv("RAGKB_EMBEDDING_BACKEND", "openai")
    cfg = Settings(
        embedding=Settings.EmbeddingConfig(
            backend="openai",
            model="USER2-small",
            base_url="http://127.0.0.1:8081/v1",
            api_key="secret",
        )
    )
    assert cfg.embedding.backend == "openai"

    assert embedding_models(cfg) == [{"id": "USER2-small"}]
    assert seen == [("http://127.0.0.1:8081/v1", "secret")]


def test_chat_catalog_hides_vector_only_models():
    """Модель, считающая только векторы, не предлагается для генерации."""
    catalog = StaticCatalog(Settings.LLMConfig(model="qwen3-embedding:0.6b"))
    service = ModelsService(
        catalog, embedding_models=lambda: [{"id": "qwen3-embedding:0.6b"}]
    )

    assert service.list() == []


def test_chat_catalog_keeps_generation_models():
    catalog = StaticCatalog(Settings.LLMConfig(model="qwen2.5:7b-instruct"))
    service = ModelsService(
        catalog, embedding_models=lambda: [{"id": "qwen3-embedding:0.6b"}]
    )

    items = service.list()

    assert [item.id for item in items] == ["qwen2.5:7b-instruct"]
    assert items[0].is_default is True


def test_chat_catalog_without_provider_lists_everything():
    catalog = StaticCatalog(Settings.LLMConfig(model="qwen3-embedding:0.6b"))

    assert [item.id for item in ModelsService(catalog).list()] == ["qwen3-embedding:0.6b"]


def test_chat_catalog_survives_broken_provider():
    """Каталог эмбеддингов недоступен — список генерации не должен падать."""
    def broken():
        raise RuntimeError("Ollama недоступна")

    catalog = StaticCatalog(Settings.LLMConfig(model="qwen2.5:7b-instruct"))

    assert [item.id for item in ModelsService(catalog, embedding_models=broken).list()] == [
        "qwen2.5:7b-instruct"
    ]
