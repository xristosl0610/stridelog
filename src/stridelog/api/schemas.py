"""Typed request and response models for the versioned local API."""

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ActivitySummary(BaseModel):
    id: int
    name: str | None
    activity_type: str
    is_race: bool
    start_time_utc: str
    utc_offset_s: int | None
    local_date: date | None
    distance_m: float | None
    timer_time_s: float | None
    elapsed_time_s: float | None
    avg_hr_bpm: float | None
    avg_cadence_spm: float | None
    hr_source: str
    dq_flags: list[str]
    is_race_override: bool | None
    race_name: str | None
    official_time_s: float | None
    notes: str | None
    excluded_from_stats: bool


class ActivityPage(BaseModel):
    items: list[ActivitySummary]
    page: int
    page_size: int
    total: int


class ActivityDetail(ActivitySummary):
    metrics: dict[str, object]


class StreamPoint(BaseModel):
    record_index: int
    ts_utc: str
    distance_m: float | None
    lat_deg: float | None
    lon_deg: float | None
    altitude_m: float | None
    speed_mps: float | None
    heart_rate_bpm: float | None
    cadence_spm: float | None


class StreamResponse(BaseModel):
    activity_id: int
    full_resolution: bool
    points: list[StreamPoint]


class GeoJsonGeometry(BaseModel):
    type: Literal["LineString"]
    coordinates: list[tuple[float, float]]


class GeoJsonFeature(BaseModel):
    type: Literal["Feature"]
    geometry: GeoJsonGeometry
    properties: dict[str, int]


class GeoJsonFeatureCollection(BaseModel):
    type: Literal["FeatureCollection"]
    features: list[GeoJsonFeature]


class VolumePoint(BaseModel):
    period_start: date
    distance_m: float
    duration_s: float
    activity_count: int


class TrendPoint(BaseModel):
    activity_id: int
    local_date: date
    distance_m: float | None
    pace_s_per_km: float | None
    avg_hr_bpm: float | None
    avg_cadence_spm: float | None
    efficiency_factor: float | None


class BestEffortEntry(BaseModel):
    activity_id: int
    local_date: date | None
    name: str | None
    distance_m: float
    duration_s: float


class RaceEntry(BaseModel):
    activity: ActivitySummary
    official_time_s: float | None
    predictions: list[dict[str, object]]


class DailyMetrics(BaseModel):
    local_date: date
    metrics: dict[str, object]


class WellnessDay(BaseModel):
    local_date: date
    resting_hr_bpm: float | None
    steps: float | None
    stress_avg: float | None
    body_battery_high: float | None
    body_battery_low: float | None
    sleep_duration_s: float | None
    sleep_score: float | None
    hrv_ms: float | None


class PredictionEntry(BaseModel):
    activity_id: int
    local_date: date | None
    name: str | None
    predictions: list[dict[str, object]]


class AnnotationUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    is_race_override: bool | None = None
    race_name: str | None = Field(default=None, max_length=200)
    official_time_s: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    notes: str | None = Field(default=None, max_length=10_000)
    exclude_from_stats: bool | None = None


class SyncRequest(BaseModel):
    since: date | None = None


class SyncStarted(BaseModel):
    job_id: str
    status: Literal["running"]


class SyncStatus(BaseModel):
    job_id: str
    status: Literal["running", "succeeded", "failed"]
    message: str | None
