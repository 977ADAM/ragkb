from alembic import op

revision = "0003_cleanup_state"
down_revision = "0002_messages"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if op.get_bind().dialect.name == "sqlite":
        op.execute(
            """
            CREATE TABLE cleanup_state (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                last_run TEXT NOT NULL
            )
            """
        )
        op.execute(
            "INSERT INTO cleanup_state (id, last_run) "
            "VALUES (1, '1970-01-01 00:00:00+00')"
        )
        return
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


def downgrade() -> None:
    op.execute("DROP TABLE cleanup_state")
