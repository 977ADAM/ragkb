import logging
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config as AlembicConfig
from fastapi.testclient import TestClient
from helpers import BACKEND_ROOT, make_app

from ragkb.core.config import Settings
from ragkb.core.logging_config import get_logger, setup_logging


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


def test_access_log_writes_method_status_and_ms(tmp_path: Path) -> None:
    """Каждый HTTP-запрос пишет access-строку с методом, статусом и временем."""
    log_dir = tmp_path / "logs"
    cfg = Settings(logging=Settings.LoggingConfig(level="INFO", dir=str(log_dir)))
    from fastapi.testclient import TestClient

    with TestClient(make_app(cfg)) as client:
        client.get("/health")
        client.get("/definitely-missing-route")
    _flush()
    text = (log_dir / "app.log").read_text(encoding="utf-8")
    assert "GET /health -> 200" in text
    assert "GET /definitely-missing-route -> 404" in text
    import re

    assert re.search(r"-> 200 \(\d+ ms\)", text)


def test_unhandled_exception_returns_json_500(tmp_path: Path) -> None:
    """Неперехваченное исключение даёт JSON 500 и попадает в errors.log."""
    log_dir = tmp_path / "logs"
    cfg = Settings(logging=Settings.LoggingConfig(level="INFO", dir=str(log_dir)))
    from fastapi.testclient import TestClient

    app = make_app(cfg)

    @app.get("/boom")
    async def boom() -> None:
        raise RuntimeError("взрыв")

    with TestClient(app, raise_server_exceptions=False) as client:
        res = client.get("/boom")
    assert res.status_code == 500
    body = res.json()
    assert body == {"detail": "Внутренняя ошибка сервера"}
    _flush()
    err = (log_dir / "errors.log").read_text(encoding="utf-8")
    assert "необработанная ошибка" in err

# ------------------------------------------------------- журнал разрешений


def _download_app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog):
    """Приложение с временным реестром: журнал проверяется на живых запросах."""
    database = tmp_path / "ragkb.sqlite3"
    url = f"sqlite+aiosqlite:///{database}"
    migration = AlembicConfig(str(BACKEND_ROOT / "alembic.ini"))
    migration.set_main_option("script_location", str(BACKEND_ROOT / "migrations"))
    monkeypatch.setenv("RAGKB_DATABASE_URL", url)
    command.upgrade(migration, "head")

    docs = tmp_path / "docs"
    docs.mkdir(exist_ok=True)
    cfg = Settings(
        docs_dir=str(docs),
        index_dir=str(tmp_path / "index"),
        logging=Settings.LoggingConfig(level="INFO", dir=str(tmp_path / "logs")),
    )
    cfg.store.backend = "memory"
    cfg.database_url = url
    app = make_app(cfg)
    # `setup_logging` внутри make_app пересобирает корневые обработчики и снимает
    # обработчик caplog: возвращаем его, иначе перехват ничего не увидит.
    logging.getLogger().addHandler(caplog.handler)
    return app


def _permission_records(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [
        record.getMessage()
        for record in caplog.records
        if "download_permission" in record.getMessage()
    ]


def test_permission_change_is_logged_with_old_new_and_request_id(
    tmp_path, monkeypatch, caplog
):
    """Успешное изменение разрешения видно в журнале с old/new и меткой запроса."""
    app = _download_app(tmp_path, monkeypatch, caplog)
    with caplog.at_level(logging.INFO, logger="ragkb"), TestClient(app) as client:
            client.post(
                "/api/v1/admin/documents",
                params={"index": "false"},
                files={"file": ("spec.pdf", b"%PDF-1.4\n", "application/pdf")},
            )
            documents = client.get("/api/v1/admin/documents").json()["corpus"]
            document_id = documents[0]["document_id"]
            response = client.patch(
                f"/api/v1/documents/{document_id}/download-permission",
                json={"download_allowed": True},
                headers={"x-request-id": "req-log"},
            )

    assert response.status_code == 200
    records = _permission_records(caplog)
    assert any(
        "result=ok" in line
        and "old=false" in line
        and "new=true" in line
        and "request_id=req-log" in line
        and document_id in line
        for line in records
    ), records
    # В журнал попадают идентификатор и значения флага, а не содержимое документа.
    assert all("spec.pdf" not in line for line in records), records


def test_refused_permission_change_is_not_logged_as_saved(tmp_path, monkeypatch, caplog):
    """Отказ не выдаётся за сохранённое изменение."""
    app = _download_app(tmp_path, monkeypatch, caplog)
    with caplog.at_level(logging.INFO, logger="ragkb"), TestClient(app) as client:
            response = client.patch(
                "/api/v1/documents/11111111-1111-4111-8111-111111111111/download-permission",
                json={"download_allowed": True},
            )

    assert response.status_code == 404
    assert _permission_records(caplog) == []


def test_download_refusal_is_logged_with_the_request_id(tmp_path, monkeypatch, caplog):
    """Отказ выдачи связывается с запросом BFF по метке."""
    app = _download_app(tmp_path, monkeypatch, caplog)
    with caplog.at_level(logging.INFO, logger="ragkb"), TestClient(app) as client:
            response = client.get(
                "/api/v1/documents/11111111-1111-4111-8111-111111111111/download",
                headers={"x-request-id": "req-download"},
            )

    assert response.status_code == 404
    refusals = [
        record.getMessage()
        for record in caplog.records
        if "result=refused" in record.getMessage()
    ]
    assert any("request_id=req-download" in line for line in refusals), refusals
    # Выдача ссылки и скачивание — разные события: аудит передачи живёт на BFF.
    assert all("download_completed" not in record.getMessage() for record in caplog.records)
