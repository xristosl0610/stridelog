"""Add an explicit steady-run annotation."""

import sqlalchemy as sa
from alembic import op

revision = "0004_steady_run_annotation"
down_revision = "0003_analytics"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    """Default existing activity annotations to not steady."""
    op.add_column(
        "activity_annotation",
        sa.Column("is_steady_run", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    """Remove the optional steady-run annotation."""
    op.drop_column("activity_annotation", "is_steady_run")
