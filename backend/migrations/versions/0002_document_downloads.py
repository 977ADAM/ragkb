"""Идентификаторы документов и разрешение на выдачу оригинала.

Добавочная миграция после начальной: реестр получает `document_id` (UUID
строкой, уникальный) и `download_allowed` (по умолчанию выключено). Прежние
записи сохраняются: каждая получает собственный идентификатор, а разрешение
остаётся закрытым — документ, загруженный до этой версии, нельзя скачать,
пока разрешение не включат явно на странице «Документы».

Схему прежних таблиц аккаунтов и переписки миграция не создаёт и не удаляет:
если они есть в базе, они остаются нетронутыми.
"""
import uuid

import sqlalchemy as sa
from alembic import op

revision = "0002_document_downloads"
down_revision = "0001_corpus_documents"
branch_labels = None
depends_on = None

UNIQUE_NAME = "uq_corpus_documents_document_id"


def upgrade() -> None:
    bind = op.get_bind()
    # Идентификатор сначала nullable: значения проставляются по строкам,
    # одним server_default все документы получили бы один и тот же UUID.
    with op.batch_alter_table("corpus_documents") as batch:
        batch.add_column(sa.Column("document_id", sa.String(36), nullable=True))
        batch.add_column(
            sa.Column(
                "download_allowed",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )
    rows = bind.execute(sa.text("SELECT name FROM corpus_documents")).scalars().all()
    for name in rows:
        bind.execute(
            sa.text("UPDATE corpus_documents SET document_id = :identifier WHERE name = :name"),
            {"identifier": str(uuid.uuid4()), "name": name},
        )
    with op.batch_alter_table("corpus_documents") as batch:
        batch.alter_column("document_id", existing_type=sa.String(36), nullable=False)
        batch.create_unique_constraint(UNIQUE_NAME, ["document_id"])


def downgrade() -> None:
    # Откат уносит только добавленные поля и ограничение: сами документы
    # остаются в реестре, но выдача оригинала становится невозможной.
    with op.batch_alter_table("corpus_documents") as batch:
        batch.drop_constraint(UNIQUE_NAME, type_="unique")
        batch.drop_column("download_allowed")
        batch.drop_column("document_id")
