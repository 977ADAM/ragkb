from pathlib import Path

import pytest

from ragkb.core.config import Config
from ragkb.platform.app import create_app


def test_history_enabled_env_false_zero_no(monkeypatch: pytest.MonkeyPatch) -> None:
    for raw in ("false", "0", "no", "FALSE"):
        cfg = Config()
        cfg.history.enabled = True
        monkeypatch.setenv("RAGKB_HISTORY_ENABLED", raw)
        cfg._apply_env()
        assert cfg.history.enabled is False, raw


def test_history_enabled_env_true_when_set(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = Config()
    cfg.history.enabled = False
    monkeypatch.setenv("RAGKB_HISTORY_ENABLED", "true")
    cfg._apply_env()
    assert cfg.history.enabled is True


def test_create_app_requires_database_url_when_history_enabled() -> None:
    cfg = Config()
    cfg.auth.mode = "disabled"
    cfg.database_url = ""
    cfg.store.backend = "numpy"
    with pytest.raises(RuntimeError, match="Задайте RAGKB_DATABASE_URL"):
        create_app(cfg)


def test_create_app_does_not_touch_repo_history(tmp_path: Path) -> None:
    """disabled + история выкл. не требует URL и не пишет sqlite."""
    cfg = Config()
    cfg.auth.mode = "disabled"
    cfg.history.enabled = False
    cfg.database_url = ""
    cfg.store.backend = "numpy"
    cfg.index_dir = str(tmp_path / "idx")
    create_app(cfg)
    backend_default = Path(__file__).resolve().parents[1].parent / "data" / "history.sqlite3"
    assert not (tmp_path / "h.sqlite3").exists()
    _ = backend_default
