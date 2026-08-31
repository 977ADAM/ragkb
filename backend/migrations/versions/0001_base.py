from alembic import op

revision = "0001_base"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS conversations (
            id         TEXT PRIMARY KEY,
            user       TEXT NOT NULL,
            title      TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_conv_user ON conversations(user, updated_at DESC)"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS messages (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
            role            TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
            text            TEXT NOT NULL,
            sources_json    TEXT NOT NULL DEFAULT '[]',
            created_at      TEXT NOT NULL
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_msg_conv ON messages(conversation_id, id)"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS cleanup_state (
            id       INTEGER PRIMARY KEY CHECK (id = 1),
            last_run TEXT NOT NULL
        )
        """
    )
    op.execute(
        "INSERT OR IGNORE INTO cleanup_state (id, last_run) "
        "VALUES (1, '1970-01-01T00:00:00+00:00')"
    )
    op.execute("PRAGMA user_version = 1")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS messages")
    op.execute("DROP TABLE IF EXISTS conversations")
    op.execute("DROP TABLE IF EXISTS cleanup_state")
    op.execute("PRAGMA user_version = 0")
