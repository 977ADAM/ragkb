from alembic import op

revision = "0002_conv_updated_index"
down_revision = "0001_base"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE INDEX IF NOT EXISTS idx_conv_updated ON conversations(updated_at)")
    op.execute("PRAGMA user_version = 2")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_conv_updated")
    op.execute("PRAGMA user_version = 1")
