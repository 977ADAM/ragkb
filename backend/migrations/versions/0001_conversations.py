from alembic import op

revision = "0001_conversations"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    if op.get_bind().dialect.name == "sqlite":
        op.execute(
            """
            CREATE TABLE conversations (
                id TEXT PRIMARY KEY,
                owner TEXT NOT NULL,
                title TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
    else:
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
    op.execute("CREATE INDEX idx_conv_owner ON conversations (owner, updated_at DESC)")
    op.execute("CREATE INDEX idx_conv_updated ON conversations (updated_at)")


def downgrade() -> None:
    op.execute("DROP TABLE conversations")
