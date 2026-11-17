"""Persistent sync bookkeeping, separate from rebuildable measurement data."""

from datetime import UTC, date, datetime
from uuid import uuid4

from sqlalchemy import JSON, CheckConstraint, Date, ForeignKey, Integer, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utc_now() -> str:
    """Represent operational instants unambiguously as ISO UTC text."""
    return datetime.now(UTC).isoformat()


class Base(DeclarativeBase):
    """Common SQLAlchemy metadata for operational migrations."""


class SyncRun(Base):
    """One attempted synchronization; error codes never contain raw exceptions."""

    __tablename__ = "sync_run"
    __table_args__ = (
        CheckConstraint("status IN ('running', 'succeeded', 'failed')", name="ck_sync_run_status"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: uuid4().hex)
    started_at_utc: Mapped[str] = mapped_column(String, default=utc_now)
    finished_at_utc: Mapped[str | None] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, default="running")
    error_code: Mapped[str | None] = mapped_column(String)


class SyncCursor(Base):
    """Last fully archived calendar day for a dataset."""

    __tablename__ = "sync_cursor"

    dataset: Mapped[str] = mapped_column(String, primary_key=True)
    through_date: Mapped[date] = mapped_column(Date)
    updated_at_utc: Mapped[str] = mapped_column(String, default=utc_now, onupdate=utc_now)


class RawFile(Base):
    """Checksum manifest for private archived files, with sync provenance."""

    __tablename__ = "raw_file"
    __table_args__ = (CheckConstraint("size_bytes >= 0", name="ck_raw_file_size"),)

    relative_path: Mapped[str] = mapped_column(String, primary_key=True)
    dataset: Mapped[str] = mapped_column(String)
    source_id: Mapped[str | None] = mapped_column(String)
    sha256: Mapped[str] = mapped_column(String(64))
    size_bytes: Mapped[int] = mapped_column(Integer)
    run_id: Mapped[str | None] = mapped_column(ForeignKey("sync_run.id"))
    updated_at_utc: Mapped[str] = mapped_column(String, default=utc_now, onupdate=utc_now)


class Activity(Base):
    """Rebuildable running summary; source checksums identify all mapping inputs."""

    __tablename__ = "activity"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str | None]
    activity_type: Mapped[str]
    event_type: Mapped[str | None]
    is_race: Mapped[bool]
    start_time_utc: Mapped[str]
    utc_offset_s: Mapped[int | None]
    end_utc_offset_s: Mapped[int | None]
    local_date: Mapped[date | None] = mapped_column(Date)
    distance_m: Mapped[float | None]
    timer_time_s: Mapped[float | None]
    elapsed_time_s: Mapped[float | None]
    avg_hr_bpm: Mapped[float | None]
    avg_cadence_spm: Mapped[float | None]
    hr_source: Mapped[str]
    hr_source_origin: Mapped[str]
    dq_flags: Mapped[list[str]] = mapped_column(JSON)
    source_checksums: Mapped[dict[str, str]] = mapped_column(JSON)
    garmin_metrics: Mapped[dict[str, float]] = mapped_column(JSON)
    parser_version: Mapped[int]


class ActivityRecord(Base):
    """Original sampling preserved; sequence key also preserves duplicate times."""

    __tablename__ = "activity_record"

    activity_id: Mapped[int] = mapped_column(ForeignKey("activity.id"), primary_key=True)
    record_index: Mapped[int] = mapped_column(primary_key=True)
    ts_utc: Mapped[str]
    distance_m: Mapped[float | None]
    lat_deg: Mapped[float | None]
    lon_deg: Mapped[float | None]
    altitude_m: Mapped[float | None]
    speed_mps: Mapped[float | None]
    heart_rate_bpm: Mapped[float | None]
    cadence_spm: Mapped[float | None]


class ActivityLap(Base):
    """FIT lap totals in SI units, without imposing auto-lap semantics."""

    __tablename__ = "activity_lap"

    activity_id: Mapped[int] = mapped_column(ForeignKey("activity.id"), primary_key=True)
    lap_index: Mapped[int] = mapped_column(primary_key=True)
    start_time_utc: Mapped[str]
    end_time_utc: Mapped[str]
    distance_m: Mapped[float | None]
    timer_time_s: Mapped[float | None]
    elapsed_time_s: Mapped[float | None]
    avg_hr_bpm: Mapped[float | None]
    avg_cadence_spm: Mapped[float | None]
    intensity: Mapped[str | None]
    trigger: Mapped[str | None]


class ActivitySensor(Base):
    """Distinct non-identifying device metadata; never persist serial numbers."""

    __tablename__ = "activity_sensor"

    activity_id: Mapped[int] = mapped_column(ForeignKey("activity.id"), primary_key=True)
    sensor_index: Mapped[int] = mapped_column(primary_key=True)
    source_type: Mapped[str | None]
    device_type: Mapped[str | None]
    manufacturer: Mapped[str | None]
    product: Mapped[str | None]
    product_name: Mapped[str | None]


class TimerEvent(Base):
    """Ordered timer events; preserve pauses without manufacturing moving time."""

    __tablename__ = "timer_event"

    activity_id: Mapped[int] = mapped_column(ForeignKey("activity.id"), primary_key=True)
    event_index: Mapped[int] = mapped_column(primary_key=True)
    ts_utc: Mapped[str]
    event_type: Mapped[str]
    trigger: Mapped[str | None]


class ActivityAnnotation(Base):
    """User-owned rows intentionally independent of rebuildable activity lifetime."""

    __tablename__ = "activity_annotation"

    activity_id: Mapped[int] = mapped_column(primary_key=True)
    is_race_override: Mapped[bool | None]
    race_name: Mapped[str | None]
    official_time_s: Mapped[float | None]
    exclude_from_stats: Mapped[bool] = mapped_column(default=False)
    hr_invalid: Mapped[bool] = mapped_column(default=False)
    notes: Mapped[str | None]


class DailyWellness(Base):
    """Daily-summary fields; missing measurements remain SQL NULL."""

    __tablename__ = "daily_wellness"

    local_date: Mapped[date] = mapped_column(Date, primary_key=True)
    resting_hr_bpm: Mapped[float | None]
    steps: Mapped[float | None]
    stress_avg: Mapped[float | None]
    body_battery_high: Mapped[float | None]
    body_battery_low: Mapped[float | None]
    raw_path: Mapped[str]
    raw_sha256: Mapped[str]


class SleepNight(Base):
    """Sleep totals in seconds, keyed by the endpoint's local calendar date."""

    __tablename__ = "sleep_night"

    local_date: Mapped[date] = mapped_column(Date, primary_key=True)
    duration_s: Mapped[float | None]
    deep_s: Mapped[float | None]
    light_s: Mapped[float | None]
    rem_s: Mapped[float | None]
    awake_s: Mapped[float | None]
    score: Mapped[float | None]
    raw_path: Mapped[str]
    raw_sha256: Mapped[str]


class HrvNight(Base):
    """Unavailable HRV is a dated NULL, not a fabricated zero."""

    __tablename__ = "hrv_night"

    local_date: Mapped[date] = mapped_column(Date, primary_key=True)
    last_night_avg_ms: Mapped[float | None]
    raw_path: Mapped[str]
    raw_sha256: Mapped[str]


class ZoneSnapshot(Base):
    """Immutable-content snapshot; do not apply today's zones to past runs."""

    __tablename__ = "zone_snapshot"

    raw_sha256: Mapped[str] = mapped_column(primary_key=True)
    sport: Mapped[str] = mapped_column(primary_key=True)
    training_method: Mapped[str | None]
    floors_bpm: Mapped[list[float | None]] = mapped_column(JSON)
    max_hr_bpm: Mapped[float | None]
    resting_hr_bpm: Mapped[float | None]
    lactate_threshold_hr_bpm: Mapped[float | None]
    raw_path: Mapped[str]
    observed_at_utc: Mapped[str]


class QualityIssue(Base):
    """Private, structured findings; codes are fixed and safe for aggregation."""

    __tablename__ = "quality_issue"

    dataset: Mapped[str] = mapped_column(primary_key=True)
    source_key: Mapped[str] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(primary_key=True)
