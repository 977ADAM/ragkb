def test_alembic_sync_url_sqlite_and_postgres() -> None:
    from ragkb.core.database import alembic_sync_url

    assert alembic_sync_url("sqlite+aiosqlite:////tmp/x.db") == "sqlite:////tmp/x.db"
    assert (
        alembic_sync_url("postgresql+asyncpg://u:p@h/db")
        == "postgresql+psycopg://u:p@h/db"
    )


def test_existing_database_is_preserved(tmp_path, monkeypatch):
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
        connection.execute("INSERT INTO users(id, username, password_hash, role, created_at) VALUES ('old-user', 'old', 'hash', 'admin', CURRENT_TIMESTAMP)")
        connection.execute("INSERT INTO corpus_documents(name, uploaded_at) VALUES ('kept.md', CURRENT_TIMESTAMP)")
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
        assert connection.execute('SELECT username FROM users').fetchall() == [('old',)]
        assert connection.execute('SELECT name FROM corpus_documents').fetchall() == [('kept.md',)]
        assert connection.execute('SELECT COUNT(*) FROM messages').fetchone()[0] == 0
        assert connection.execute('SELECT COUNT(*) FROM conversations').fetchone()[0] == 0
