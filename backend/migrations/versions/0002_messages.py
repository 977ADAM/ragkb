from alembic import op

revision = "0002_messages"
down_revision = "0001_conversations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if op.get_bind().dialect.name == "sqlite":
        op.execute(
            """
            CREATE TABLE messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
                role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
                text TEXT NOT NULL,
                sources TEXT NOT NULL DEFAULT '[]',
                model TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            )
            """
        )
    else:
        op.execute(
            """
            CREATE TABLE messages (
                id BIGSERIAL PRIMARY KEY,
                conversation_id UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
                role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
                text TEXT NOT NULL,
                sources JSONB NOT NULL DEFAULT '[]'::jsonb,
                model TEXT NOT NULL DEFAULT '',
                created_at TIMESTAMPTZ NOT NULL
            )
            """
        )
    op.execute("CREATE INDEX idx_msg_conv ON messages (conversation_id, id)")


def downgrade() -> None:
    op.execute("DROP TABLE messages")
