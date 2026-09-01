from alembic import op

revision = "0001_postgres_history_auth"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE conversations (
            id UUID PRIMARY KEY,
            owner TEXT NOT NULL,
            title TEXT NOT NULL DEFAULT '',
            created_at TIMESTAMPTZ NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL
        )
        """
    )
    op.execute(
        "CREATE INDEX idx_conv_owner ON conversations (owner, updated_at DESC)"
    )
    op.execute("CREATE INDEX idx_conv_updated ON conversations (updated_at)")
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
    op.execute(
        """
        CREATE TABLE cleanup_state (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            last_run TIMESTAMPTZ NOT NULL
        )
        """
    )
    op.execute(
        "INSERT INTO cleanup_state (id, last_run) "
        "VALUES (1, TIMESTAMPTZ '1970-01-01 00:00:00+00')"
    )
    op.execute(
        """
        CREATE TABLE users (
            id UUID PRIMARY KEY,
            username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL
        )
        """
    )
    op.execute(
        """
        CREATE TABLE sessions (
            token_hash TEXT PRIMARY KEY,
            user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            expires_at TIMESTAMPTZ NOT NULL
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS sessions")
    op.execute("DROP TABLE IF EXISTS users")
    op.execute("DROP TABLE IF EXISTS messages")
    op.execute("DROP TABLE IF EXISTS conversations")
    op.execute("DROP TABLE IF EXISTS cleanup_state")
