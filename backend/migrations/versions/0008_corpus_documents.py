"""Таблица реестра документов корпуса.

Реестр — источник истины о том, что принадлежит базе знаний: индекс
собирается по нему, поэтому файл, положенный в каталог мимо интерфейса,
в ответы не попадёт, пока его не примут на странице документов.
"""
from alembic import op

revision = "0008_corpus_documents"
down_revision = "0007_message_feedback"
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
