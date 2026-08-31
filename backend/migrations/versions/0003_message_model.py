from alembic import op

revision = "0003_message_model"
down_revision = "0002_conv_updated_index"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE messages ADD COLUMN model TEXT NOT NULL DEFAULT ''")
    op.execute("PRAGMA user_version = 3")


def downgrade() -> None:
    op.execute("ALTER TABLE messages DROP COLUMN model")
    op.execute("PRAGMA user_version = 2")
