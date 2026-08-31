from ragkb.core.config import LLMConfig
from ragkb.features.models.ollama import OllamaCatalog
from ragkb.features.models.static import StaticCatalog


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
