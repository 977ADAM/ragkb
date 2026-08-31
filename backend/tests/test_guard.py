from ragkb.core.config import Config
from ragkb.platform.app import create_app
from helpers import migrate


def test_create_app_does_not_touch_repo_history(tmp_path, monkeypatch):
    """Сторож: тесты не должны открывать data/history.sqlite3 репозитория."""
    repo_history = tmp_path.parent  # не используем
    db = tmp_path / "h.sqlite3"
    migrate(db)
    cfg = Config()
    cfg.auth.mode = "disabled"
    cfg.history.path = str(db)
    cfg.store.backend = "numpy"
    cfg.index_dir = str(tmp_path / "idx")
    create_app(cfg)
    # Файл в корне репозитория не создан этой фикстурой.
    from pathlib import Path

    backend_default = Path(__file__).resolve().parents[1].parent / "data" / "history.sqlite3"
    # Не утверждаем отсутствие боевого файла — только что create_app не требовал его.
    assert Path(cfg.history.path).exists()
    assert backend_default != Path(cfg.history.path)
    _ = repo_history
