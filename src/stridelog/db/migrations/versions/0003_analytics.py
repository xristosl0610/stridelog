"""Add user-owned athlete settings and rebuildable analytics tables."""

import sqlalchemy as sa
from alembic import op

revision = "0003_analytics"
down_revision = "0002_measurements"
branch_labels: str | None = None
depends_on: str | None = None


def _floats(*names: str) -> list[sa.Column[float]]:
    return [sa.Column(name, sa.Double(), nullable=True) for name in names]


def upgrade() -> None:
    """Add dated profile inputs and derived metric caches."""
    op.create_table(
        "athlete_profile",
        sa.Column("effective_from", sa.Date(), primary_key=True),
        *_floats("max_hr_bpm", "resting_hr_bpm", "threshold_hr_bpm"),
        sa.Column("sex_for_trimp", sa.String(), nullable=True),
        sa.Column("hr_zone_floors_bpm", sa.JSON(), nullable=True),
        sa.CheckConstraint(
            "sex_for_trimp IS NULL OR sex_for_trimp IN ('female', 'other')",
            name="ck_athlete_profile_sex_for_trimp",
        ),
    )
    op.create_table(
        "activity_analytics",
        sa.Column("activity_id", sa.Integer(), primary_key=True),
        sa.Column("input_signature", sa.String(64), nullable=False),
        sa.Column("algorithm_version", sa.Integer(), nullable=False),
        sa.Column("metrics", sa.JSON(), nullable=False),
    )
    op.create_table(
        "daily_analytics",
        sa.Column("local_date", sa.Date(), primary_key=True),
        sa.Column("metrics", sa.JSON(), nullable=False),
    )


def downgrade() -> None:
    """Remove only Phase 4 tables; measurements and user annotations survive."""
    op.drop_table("daily_analytics")
    op.drop_table("activity_analytics")
    op.drop_table("athlete_profile")
