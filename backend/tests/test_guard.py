def test_alembic_sync_url_sqlite_and_postgres() -> None:
    from ragkb.core.database import alembic_sync_url

    assert alembic_sync_url("sqlite+aiosqlite:////tmp/x.db") == "sqlite:////tmp/x.db"
    assert (
        alembic_sync_url("postgresql+asyncpg://u:p@h/db")
        == "postgresql+psycopg://u:p@h/db"
    )


def test_upgrade_head_is_idempotent_and_registry_persists(tmp_path, monkeypatch):
    import sqlite3
    from alembic import command
    from alembic.config import Config
    from fastapi.testclient import TestClient
    from helpers import BACKEND_ROOT, make_app
    from ragkb.core.config import Settings

    path = tmp_path / 'existing.sqlite3'
    url = f'sqlite+aiosqlite:///{path}'
    monkeypatch.setenv('RAGKB_DATABASE_URL', url)
    migration = Config(str(BACKEND_ROOT / 'alembic.ini'))
    migration.set_main_option('script_location', str(BACKEND_ROOT / 'migrations'))
    command.upgrade(migration, 'head')
    with sqlite3.connect(path) as connection:
        # Запись реестра без идентификатора схема больше не принимает: он
        # обязателен с ревизии 0002.
        connection.execute(
            "INSERT INTO corpus_documents(name, document_id, uploaded_at)"
            " VALUES ('kept.md', '11111111-1111-4111-8111-111111111111', CURRENT_TIMESTAMP)"
        )
    # Повторный upgrade не падает и не трогает принятые документы.
    command.upgrade(migration, 'head')
    cfg = Settings(docs_dir=str(tmp_path / 'docs'), index_dir=str(tmp_path / 'index'))
    cfg.database_url = url
    cfg.logging.dir = str(tmp_path / 'logs')
    with TestClient(make_app(cfg)) as client:
        assert client.get('/health').status_code == 200
        assert client.get('/api/v1/admin/documents').json()['registry'] == 'on'
        assert client.post('/api/v1/ask', json={'question': 'Вопрос?'}).status_code == 503
        assert client.post('/api/v1/auths/signin', json={}).status_code == 404
    with sqlite3.connect(path) as connection:
        assert connection.execute('SELECT name FROM corpus_documents').fetchall() == [('kept.md',)]
        # Аккаунтов и переписки схема больше не создаёт вовсе.
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        assert tables == {'alembic_version', 'corpus_documents'}
