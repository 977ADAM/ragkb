"""Начальная миграция: таблица реестра документов корпуса.

Единственная миграция проекта. Прежняя цепочка из восьми ревизий удалена
вместе с аккаунтами, сессиями, перепиской и оценками: приложению нужна
только эта таблица. Схема прежних таблиц в уже существующих базах здесь
не создаётся и не удаляется — обновление не стирает данные. Базу, стоящую
на старой ревизии, помечают так:

    alembic stamp --purge 0001_corpus_documents

`--purge` обязателен: прежней ревизии больше нет в каталоге версий, поэтому
обычный stamp не может разрешить текущее значение в alembic_version.

Реестр — источник истины о том, что принадлежит базе знаний: индекс
собирается по нему, поэтому файл, положенный в каталог мимо интерфейса,
в ответы не попадёт, пока его не примут на странице документов.
"""
from alembic import op

revision = "0001_corpus_documents"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    if op.get_bind().dialect.name == "sqlite":
        op.execute(
            """
            CREATE TABLE corpus_documents (
                name TEXT PRIMARY KEY,
                origin TEXT NOT NULL DEFAULT 'ui',
                uploaded_by TEXT NOT NULL DEFAULT '',
                uploaded_at TEXT NOT NULL,
                size INTEGER NOT NULL DEFAULT 0,
                sha256 TEXT NOT NULL DEFAULT ''
            )
            """
        )
        return
    op.execute(
        """
        CREATE TABLE corpus_documents (
            name TEXT PRIMARY KEY,
            origin TEXT NOT NULL DEFAULT 'ui',
            uploaded_by TEXT NOT NULL DEFAULT '',
            uploaded_at TIMESTAMPTZ NOT NULL,
            size BIGINT NOT NULL DEFAULT 0,
            sha256 TEXT NOT NULL DEFAULT ''
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE corpus_documents")
