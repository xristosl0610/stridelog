"""Rebuildable measurements and independently preserved user annotations."""

import sqlalchemy as sa
from alembic import op

revision = "0002_measurements"
down_revision = "0001_operations"
branch_labels: str | None = None
depends_on: str | None = None


def _activity_key(index: str) -> list[sa.Column[int]]:
    return [
        sa.Column("activity_id", sa.Integer(), sa.ForeignKey("activity.id"), primary_key=True),
        sa.Column(index, sa.Integer(), primary_key=True),
    ]


def _floats(*names: str) -> list[sa.Column[float]]:
    return [sa.Column(name, sa.Double(), nullable=True) for name in names]


def _texts(*names: str) -> list[sa.Column[str]]:
    return [sa.Column(name, sa.String(), nullable=True) for name in names]


def _provenance() -> list[sa.Column[str]]:
    return [
        sa.Column("raw_path", sa.String(), nullable=False),
        sa.Column("raw_sha256", sa.String(), nullable=False),
    ]


def upgrade() -> None:
    """Keep operational rows unchanged and add only Phase 3 tables."""
    op.create_table(
        "activity",
        sa.Column("id", sa.Integer(), primary_key=True),
        *_texts("name", "event_type"),
        sa.Column("activity_type", sa.String(), nullable=False),
        sa.Column("is_race", sa.Boolean(), nullable=False),
        sa.Column("start_time_utc", sa.String(), nullable=False),
        sa.Column("utc_offset_s", sa.Integer(), nullable=True),
        sa.Column("end_utc_offset_s", sa.Integer(), nullable=True),
        sa.Column("local_date", sa.Date(), nullable=True),
        *_floats("distance_m", "timer_time_s", "elapsed_time_s", "avg_hr_bpm", "avg_cadence_spm"),
        sa.Column("hr_source", sa.String(), nullable=False),
        sa.Column("hr_source_origin", sa.String(), nullable=False),
        sa.Column("dq_flags", sa.JSON(), nullable=False),
        sa.Column("source_checksums", sa.JSON(), nullable=False),
        sa.Column("garmin_metrics", sa.JSON(), nullable=False),
        sa.Column("parser_version", sa.Integer(), nullable=False),
    )
    op.create_table(
        "activity_record",
        *_activity_key("record_index"),
        sa.Column("ts_utc", sa.String(), nullable=False),
        *_floats(
            "distance_m",
            "lat_deg",
            "lon_deg",
            "altitude_m",
            "speed_mps",
            "heart_rate_bpm",
            "cadence_spm",
        ),
    )
    op.create_table(
        "activity_lap",
        *_activity_key("lap_index"),
        sa.Column("start_time_utc", sa.String(), nullable=False),
        sa.Column("end_time_utc", sa.String(), nullable=False),
        *_floats("distance_m", "timer_time_s", "elapsed_time_s", "avg_hr_bpm", "avg_cadence_spm"),
        *_texts("intensity", "trigger"),
    )
    op.create_table(
        "activity_sensor",
        *_activity_key("sensor_index"),
        *_texts("source_type", "device_type", "manufacturer", "product", "product_name"),
    )
    op.create_table(
        "timer_event",
        *_activity_key("event_index"),
        sa.Column("ts_utc", sa.String(), nullable=False),
        sa.Column("event_type", sa.String(), nullable=False),
        *_texts("trigger"),
    )
    op.create_table(
        "activity_annotation",
        sa.Column("activity_id", sa.Integer(), primary_key=True),
        sa.Column("is_race_override", sa.Boolean(), nullable=True),
        *_texts("race_name", "notes"),
        *_floats("official_time_s"),
        sa.Column("exclude_from_stats", sa.Boolean(), nullable=False),
        sa.Column("hr_invalid", sa.Boolean(), nullable=False),
    )
    op.create_table(
        "daily_wellness",
        sa.Column("local_date", sa.Date(), primary_key=True),
        *_floats("resting_hr_bpm", "steps", "stress_avg", "body_battery_high", "body_battery_low"),
        *_provenance(),
    )
    op.create_table(
        "sleep_night",
        sa.Column("local_date", sa.Date(), primary_key=True),
        *_floats("duration_s", "deep_s", "light_s", "rem_s", "awake_s", "score"),
        *_provenance(),
    )
    op.create_table(
        "hrv_night",
        sa.Column("local_date", sa.Date(), primary_key=True),
        *_floats("last_night_avg_ms"),
        *_provenance(),
    )
    op.create_table(
        "zone_snapshot",
        sa.Column("raw_sha256", sa.String(), primary_key=True),
        sa.Column("sport", sa.String(), primary_key=True),
        *_texts("training_method"),
        sa.Column("floors_bpm", sa.JSON(), nullable=False),
        *_floats("max_hr_bpm", "resting_hr_bpm", "lactate_threshold_hr_bpm"),
        sa.Column("raw_path", sa.String(), nullable=False),
        sa.Column("observed_at_utc", sa.String(), nullable=False),
    )
    op.create_table(
        "quality_issue",
        sa.Column("dataset", sa.String(), primary_key=True),
        sa.Column("source_key", sa.String(), primary_key=True),
        sa.Column("code", sa.String(), primary_key=True),
    )


def downgrade() -> None:
    """Explicit downgrades remove measurement and annotation tables."""
    for name in (
        "quality_issue",
        "zone_snapshot",
        "hrv_night",
        "sleep_night",
        "daily_wellness",
        "activity_annotation",
        "timer_event",
        "activity_sensor",
        "activity_lap",
        "activity_record",
        "activity",
    ):
        op.drop_table(name)
