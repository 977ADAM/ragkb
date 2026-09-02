from alembic import op

revision = "0007_message_feedback"
down_revision = "0006_user_role"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if op.get_bind().dialect.name == "sqlite":
        op.execute(
            """
            CREATE TABLE message_feedback (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                message_id INTEGER NOT NULL UNIQUE REFERENCES messages(id) ON DELETE CASCADE,
                rating TEXT NOT NULL CHECK (rating IN ('up', 'down')),
                comment TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
    else:
        op.execute(
            """
            CREATE TABLE message_feedback (
                id BIGSERIAL PRIMARY KEY,
                message_id BIGINT NOT NULL UNIQUE REFERENCES messages(id) ON DELETE CASCADE,
                rating TEXT NOT NULL CHECK (rating IN ('up', 'down')),
                comment TEXT NOT NULL DEFAULT '',
                created_at TIMESTAMPTZ NOT NULL,
                updated_at TIMESTAMPTZ NOT NULL
            )
            """
        )


def downgrade() -> None:
    op.execute("DROP TABLE message_feedback")
