from alembic import op

revision = "0006_user_role"
down_revision = "0005_sessions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if op.get_bind().dialect.name == "sqlite":
        op.execute(
            """
            ALTER TABLE users ADD COLUMN role TEXT NOT NULL DEFAULT 'user'
            """
        )
        return
    op.execute(
        """
        ALTER TABLE users ADD COLUMN role TEXT NOT NULL DEFAULT 'user'
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE users DROP COLUMN role")
