from ragkb.core.config import LLMConfig
from ragkb.features.models.ollama import OllamaCatalog
from ragkb.features.models.openai import OpenAICatalog
from ragkb.features.models.static import StaticCatalog


def test_openai_catalog_short_name_for_gguf_path():
    cfg = LLMConfig(
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
    cfg = LLMConfig(backend="openai", model="a", available=[{"name": "a"}])
    cat = OpenAICatalog(
        cfg,
        installed=[{"id": "a"}, {"id": "b"}],
    )
    assert {m.id for m in cat.list()} == {"a"}
    empty = OpenAICatalog(LLMConfig(backend="openai", model="local"), installed=[])
    assert empty.list()[0].id == "local"


def test_static_catalog_default():
    cat = StaticCatalog(LLMConfig(model="local-gguf"))
    assert cat.list()[0].id == "local-gguf"
    assert cat.resolve(None) == "local-gguf"


def test_ollama_catalog_filters_and_resolve():
    cfg = LLMConfig(backend="ollama", model="a", available=[{"name": "a"}])
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
