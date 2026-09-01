import logging
from pathlib import Path

from ragkb.core.config import Config, LoggingConfig, OrganizationConfig
from ragkb.core.logging_config import get_logger, setup_logging
from ragkb.platform.app import create_app


def _flush() -> None:
    for handler in logging.getLogger().handlers:
        handler.flush()


def test_setup_logging_writes_info_and_errors(tmp_path: Path) -> None:
    setup_logging(level="INFO", log_dir=tmp_path)
    log = get_logger("ragkb")
    log.info("hello-info")
    log.error("hello-error")
    _flush()
    app = (tmp_path / "app.log").read_text(encoding="utf-8")
    err = (tmp_path / "errors.log").read_text(encoding="utf-8")
    assert "hello-info" in app
    assert "hello-error" in app
    assert "hello-error" in err
    assert "hello-info" not in err


def test_setup_logging_rebinds_directory(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    setup_logging(level="INFO", log_dir=first)
    get_logger("ragkb").info("in-first")
    setup_logging(level="INFO", log_dir=second)
    get_logger("ragkb").info("in-second")
    _flush()
    assert "in-second" in (second / "app.log").read_text(encoding="utf-8")
    assert "in-second" not in (first / "app.log").read_text(encoding="utf-8")


def test_create_app_logs_disabled_auth_to_configured_dir(tmp_path: Path) -> None:
    log_dir = tmp_path / "logs"
    cfg = Config(
        organization=OrganizationConfig(name="Acme", id="acme"),
        logging=LoggingConfig(level="INFO", dir=str(log_dir)),
    )
    cfg.auth.mode = "disabled"
    cfg.history.enabled = False
    create_app(cfg)
    _flush()
    text = (log_dir / "app.log").read_text(encoding="utf-8")
    assert "аутентификация выключена" in text
