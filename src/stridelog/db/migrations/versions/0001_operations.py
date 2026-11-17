"""Create persistent sync runs, cursors and raw-file manifest."""

import sqlalchemy as sa
from alembic import op

revision = "0001_operations"
down_revision: str | None = None
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    """Create only operational tables; measurement schemas remain Phase 3."""
    op.create_table(
        "sync_run",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("started_at_utc", sa.String(), nullable=False),
        sa.Column("finished_at_utc", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("error_code", sa.String(), nullable=True),
        sa.CheckConstraint(
            "status IN ('running', 'succeeded', 'failed')", name="ck_sync_run_status"
        ),
    )
    op.create_table(
        "sync_cursor",
        sa.Column("dataset", sa.String(), primary_key=True),
        sa.Column("through_date", sa.Date(), nullable=False),
        sa.Column("updated_at_utc", sa.String(), nullable=False),
    )
    op.create_table(
        "raw_file",
        sa.Column("relative_path", sa.String(), primary_key=True),
        sa.Column("dataset", sa.String(), nullable=False),
        sa.Column("source_id", sa.String(), nullable=True),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.String(), sa.ForeignKey("sync_run.id"), nullable=True),
        sa.Column("updated_at_utc", sa.String(), nullable=False),
        sa.CheckConstraint("size_bytes >= 0", name="ck_raw_file_size"),
    )


def downgrade() -> None:
    """Remove operations only when explicitly requested through Alembic."""
    op.drop_table("raw_file")
    op.drop_table("sync_cursor")
    op.drop_table("sync_run")
