"""Offline analysis orchestration over typed local measurements."""

import hashlib
import json
import math
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from itertools import pairwise
from typing import cast

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from stridelog.analytics import (
    ANALYTICS_VERSION,
    DISTANCE_INTERPOLATION_GAP_S,
    AthleteInputs,
    EffortLap,
    PreparedPoint,
    SamplePoint,
    aerobic_decoupling_percent,
    calculate_best_efforts,
    calculate_lap_effort,
    calculate_splits,
    efficiency_factor,
    grade_adjusted_pace_s_per_km,
    moving_time_s,
    pace_at_heart_rate_s_per_km,
    prepare_stream,
    race_predictions,
    time_in_zones_s,
    trimp,
)
from stridelog.config import Settings
from stridelog.db.engine import DATABASE_NAME, database_engine, initialize_database
from stridelog.db.models import (
    Activity,
    ActivityAnalytics,
    ActivityAnnotation,
    ActivityLap,
    ActivityRecord,
    AthleteProfile,
    DailyAnalytics,
    DailyWellness,
    HrvNight,
    SleepNight,
    TimerEvent,
)
from stridelog.errors import StridelogError
from stridelog.ingest.locking import sync_lock

RACE_TARGETS_M = (5_000.0, 10_000.0, 21_097.5, 42_195.0)


@dataclass(frozen=True)
class AnalysisReport:
    """Aggregate progress only; never expose activity identifiers or metrics."""

    calculated_activities: int
    skipped_activities: int
    calculated_days: int


def _signature(
    activity: Activity,
    annotation: ActivityAnnotation | None,
    profile: AthleteProfile | None,
) -> str:
    data = {
        "version": ANALYTICS_VERSION,
        "source_checksums": activity.source_checksums,
        "parser_version": activity.parser_version,
        "profile": None
        if profile is None
        else {
            "effective_from": profile.effective_from.isoformat(),
            "max_hr_bpm": profile.max_hr_bpm,
            "resting_hr_bpm": profile.resting_hr_bpm,
            "sex_for_trimp": profile.sex_for_trimp,
            "hr_zone_floors_bpm": profile.hr_zone_floors_bpm,
        },
        "annotation": None
        if annotation is None
        else {
            "exclude_from_stats": annotation.exclude_from_stats,
            "hr_invalid": annotation.hr_invalid,
            "is_race_override": annotation.is_race_override,
            "is_steady_run": annotation.is_steady_run,
            "official_time_s": annotation.official_time_s,
        },
    }
    return hashlib.sha256(
        json.dumps(data, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def _sample_rows(session: Session, activity_id: int) -> list[SamplePoint]:
    records = session.scalars(
        select(ActivityRecord)
        .where(ActivityRecord.activity_id == activity_id)
        .order_by(ActivityRecord.record_index)
    )
    return [
        SamplePoint(
            _instant(row.ts_utc),
            row.distance_m,
            row.altitude_m,
            row.speed_mps,
            row.heart_rate_bpm,
            row.cadence_spm,
        )
        for row in records
    ]


def _instant(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.utcoffset() is None:
        raise StridelogError("Naive sample timestamp found; run rebuild and inspect its report.")
    return parsed


def _profile_at(
    profiles: list[AthleteProfile], activity_date: date | None
) -> AthleteProfile | None:
    if activity_date is None:
        return None
    return next(
        (profile for profile in reversed(profiles) if profile.effective_from <= activity_date),
        None,
    )


def _profile_inputs(profile: AthleteProfile | None) -> AthleteInputs | None:
    if profile is None:
        return None
    return AthleteInputs(
        profile.max_hr_bpm,
        profile.resting_hr_bpm,
        profile.sex_for_trimp,
        None if profile.hr_zone_floors_bpm is None else tuple(profile.hr_zone_floors_bpm),
    )


def _lap_metrics(laps: list[ActivityLap]) -> list[dict[str, float | int | None]]:
    return [
        {
            "lap_index": lap.lap_index,
            "distance_m": lap.distance_m,
            "timer_time_s": lap.timer_time_s,
            "pace_s_per_km": (
                None
                if not lap.distance_m or not lap.timer_time_s
                else lap.timer_time_s / lap.distance_m * 1_000
            ),
            "avg_hr_bpm": lap.avg_hr_bpm,
            "avg_cadence_spm": lap.avg_cadence_spm,
        }
        for lap in laps
    ]


def _elevation_gain(points: tuple[PreparedPoint, ...]) -> float | None:
    elevations = [point.altitude_m for point in points]
    if not any(value is not None for value in elevations):
        return None
    return sum(
        max(0.0, right - left)
        for left, right in pairwise(elevations)
        if left is not None and right is not None
    )


def _activity_metrics(
    session: Session,
    activity: Activity,
    annotation: ActivityAnnotation | None,
    profile: AthleteProfile | None,
) -> dict[str, object]:
    samples = _sample_rows(session, activity.id)
    timer_events = [
        (_instant(event.ts_utc), event.event_type)
        for event in session.scalars(
            select(TimerEvent)
            .where(TimerEvent.activity_id == activity.id)
            .order_by(TimerEvent.event_index)
        )
    ]
    points = prepare_stream(samples, timer_events=timer_events)
    distance_points = prepare_stream(
        samples, timer_events=timer_events, max_gap_s=DISTANCE_INTERPOLATION_GAP_S
    )
    invalid_hr = annotation is not None and annotation.hr_invalid
    duration = moving_time_s(points, activity.timer_time_s)
    efforts = calculate_best_efforts(distance_points)
    laps = list(
        session.scalars(
            select(ActivityLap)
            .where(ActivityLap.activity_id == activity.id)
            .order_by(ActivityLap.lap_index)
        )
    )
    lap_marathon = (
        None
        if any(effort.distance_m == 42_195 for effort in efforts)
        else calculate_lap_effort(
            [
                EffortLap(
                    lap.lap_index,
                    _instant(lap.start_time_utc),
                    _instant(lap.end_time_utc),
                    lap.distance_m,
                    lap.timer_time_s,
                    lap.elapsed_time_s,
                )
                for lap in laps
            ],
            42_195,
        )
    )
    is_race = (
        activity.is_race
        if annotation is None or annotation.is_race_override is None
        else (annotation.is_race_override)
    )
    race_time = (
        annotation.official_time_s
        if annotation is not None and annotation.official_time_s is not None
        else activity.timer_time_s
    )
    predictions = (
        race_predictions(
            activity.distance_m,
            race_time,
            efforts,
            RACE_TARGETS_M,
        )
        if is_race and activity.distance_m is not None and race_time is not None
        else ()
    )
    profile_inputs = _profile_inputs(profile)
    return {
        "moving_time_s": duration,
        "splits": [asdict(item) for item in calculate_splits(distance_points)],
        "laps": _lap_metrics(laps),
        "best_efforts": [asdict(item) for item in efforts],
        "lap_estimated_marathon": None if lap_marathon is None else asdict(lap_marathon),
        "time_in_zones_s": time_in_zones_s(
            points,
            None if profile_inputs is None else profile_inputs.hr_zone_floors_bpm,
            invalid_hr=invalid_hr,
        ),
        "training_load_trimp": trimp(points, profile_inputs, invalid_hr=invalid_hr),
        "efficiency_factor": efficiency_factor(points, invalid_hr=invalid_hr),
        "pace_at_hr_140_150_s_per_km": pace_at_heart_rate_s_per_km(points, invalid_hr=invalid_hr),
        "aerobic_decoupling_percent": aerobic_decoupling_percent(
            points,
            duration,
            is_steady_run=annotation is not None and annotation.is_steady_run,
            invalid_hr=invalid_hr,
        ),
        "grade_adjusted_pace_s_per_km": grade_adjusted_pace_s_per_km(points),
        "elevation_gain_m": _elevation_gain(points),
        "race_predictions": [asdict(item) for item in predictions],
    }


def _optional_mean(values: list[float | None]) -> float | None:
    available = [value for value in values if value is not None and math.isfinite(value)]
    return None if not available else sum(available) / len(available)


def _daily_metrics(session: Session, activities: list[Activity]) -> int:
    annotations = {row.activity_id: row for row in session.scalars(select(ActivityAnnotation))}
    by_day: dict[date, list[Activity]] = {}
    for activity in activities:
        if activity.local_date is not None:
            by_day.setdefault(activity.local_date, []).append(activity)
    wellness = {row.local_date: row for row in session.scalars(select(DailyWellness))}
    sleep = {row.local_date: row for row in session.scalars(select(SleepNight))}
    hrv = {row.local_date: row for row in session.scalars(select(HrvNight))}
    dates = set(by_day) | set(wellness) | set(sleep) | set(hrv)
    session.execute(delete(DailyAnalytics))
    if not dates:
        return 0

    daily_loads: dict[date, float | None] = {}
    cached: dict[int, dict[str, object]] = {
        item.activity_id: item.metrics for item in session.scalars(select(ActivityAnalytics))
    }
    progression = personal_record_progression(activities, annotations, cached)
    weekly_paces: dict[date, list[float]] = {}
    for day, entries in by_day.items():
        loads: list[float] = []
        unknown = False
        for activity in entries:
            annotation = annotations.get(activity.id)
            if annotation is not None and annotation.exclude_from_stats:
                continue
            load = cached.get(activity.id, {}).get("training_load_trimp")
            if annotation is not None and annotation.hr_invalid:
                continue
            if isinstance(load, int | float) and not isinstance(load, bool):
                loads.append(float(load))
            else:
                unknown = True
        daily_loads[day] = None if unknown else sum(loads)
    for activity in activities:
        if activity.local_date is None:
            continue
        annotation = annotations.get(activity.id)
        if annotation is not None and (annotation.exclude_from_stats or annotation.hr_invalid):
            continue
        pace = cached.get(activity.id, {}).get("pace_at_hr_140_150_s_per_km")
        if isinstance(pace, int | float) and not isinstance(pace, bool):
            week = activity.local_date - timedelta(days=activity.local_date.weekday())
            weekly_paces.setdefault(week, []).append(float(pace))

    day = min(dates)
    last = max(dates)
    calculated_days = 0
    load_history: list[float | None] = []
    ctl: float | None = 0.0
    atl: float | None = 0.0
    while day <= last:
        load = daily_loads.get(day, 0.0)
        load_history.append(load)
        previous_ctl, previous_atl = ctl, atl
        if load is None or ctl is None or atl is None:
            ctl = atl = None
        else:
            ctl = ctl + (load - ctl) / 42
            atl = atl + (load - atl) / 7
        acute_chronic = _ratio(load_history[-7:], load_history[-28:])
        ramp_rate = _ramp_rate(load_history)
        wellness_row = wellness.get(day)
        sleep_row = sleep.get(day)
        hrv_row = hrv.get(day)
        week_start = day - timedelta(days=day.weekday())
        weekly_pace_values = weekly_paces.get(week_start, [])
        resting_window = [
            item.resting_hr_bpm
            for date_key, item in wellness.items()
            if day - timedelta(days=6) <= date_key <= day
        ]
        session.add(
            DailyAnalytics(
                local_date=day,
                metrics={
                    "training_load_trimp": load,
                    "ctl": ctl,
                    "atl": atl,
                    "tsb": (
                        None
                        if previous_ctl is None or previous_atl is None
                        else previous_ctl - previous_atl
                    ),
                    "acute_chronic_workload_ratio": acute_chronic,
                    "weekly_ramp_rate_percent": ramp_rate,
                    "pace_at_hr_140_150_weekly_median_s_per_km": (
                        None if not weekly_pace_values else _median(weekly_pace_values)
                    ),
                    "personal_records_progression": progression.get(day, []),
                    "resting_hr_7d_avg_bpm": _optional_mean(resting_window),
                    "sleep_duration_s": None if sleep_row is None else sleep_row.duration_s,
                    "steps": None if wellness_row is None else wellness_row.steps,
                    "body_battery_high": (
                        None if wellness_row is None else wellness_row.body_battery_high
                    ),
                    "body_battery_low": (
                        None if wellness_row is None else wellness_row.body_battery_low
                    ),
                    "stress_avg": None if wellness_row is None else wellness_row.stress_avg,
                    "hrv_ms": None if hrv_row is None else hrv_row.last_night_avg_ms,
                },
            )
        )
        calculated_days += 1
        day += timedelta(days=1)
    return calculated_days


def _object_rows(value: object) -> list[object]:
    if not isinstance(value, list):
        return []
    return cast("list[object]", value)


def _mapping_value(value: object, key: str) -> object:
    if not isinstance(value, dict):
        return None
    mapping = cast("dict[str, object]", value)
    return mapping.get(key)


def _median(values: list[float]) -> float:
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2


def personal_record_progression(
    activities: list[Activity],
    annotations: dict[int, ActivityAnnotation],
    cached: dict[int, dict[str, object]],
) -> dict[date, list[dict[str, float]]]:
    records: dict[float, float] = {}
    progression: dict[date, list[dict[str, float]]] = {}
    for activity in sorted(
        (item for item in activities if item.local_date is not None),
        key=lambda item: (item.local_date, item.id),
    ):
        activity_date = activity.local_date
        if activity_date is None:
            continue
        annotation = annotations.get(activity.id)
        if annotation is not None and annotation.exclude_from_stats:
            continue
        efforts = _object_rows(cached.get(activity.id, {}).get("best_efforts"))
        for effort in efforts:
            distance = _mapping_value(effort, "distance_m")
            duration = _mapping_value(effort, "duration_s")
            if (
                not isinstance(distance, int | float)
                or isinstance(distance, bool)
                or not isinstance(duration, int | float)
                or isinstance(duration, bool)
            ):
                continue
            key = float(distance)
            value = float(duration)
            if key not in records or value < records[key]:
                progression.setdefault(activity_date, []).append(
                    {"distance_m": key, "time_s": value}
                )
                records[key] = value
    return progression


def _ratio(acute: list[float | None], chronic: list[float | None]) -> float | None:
    if len(acute) < 7 or len(chronic) < 28 or any(value is None for value in chronic):
        return None
    if any(value is None for value in acute):
        return None
    acute_mean = sum(value for value in acute if value is not None) / 7
    chronic_mean = sum(value for value in chronic if value is not None) / 28
    return None if chronic_mean == 0 else acute_mean / chronic_mean


def _ramp_rate(load_history: list[float | None]) -> float | None:
    if len(load_history) < 14:
        return None
    previous, current = load_history[-14:-7], load_history[-7:]
    if any(value is None for value in previous + current):
        return None
    previous_sum = sum(value for value in previous if value is not None)
    if previous_sum == 0:
        return None
    current_sum = sum(value for value in current if value is not None)
    return (current_sum - previous_sum) / previous_sum * 100


def analyze(settings: Settings) -> AnalysisReport:
    """Cache per-activity results by signature and replace the daily series."""
    if not (settings.data_dir / DATABASE_NAME).is_file():
        raise StridelogError("No local database; run sync and rebuild first.")
    with sync_lock(settings.data_dir):
        initialize_database(settings.data_dir)
        engine = database_engine(settings.data_dir)
        try:
            with Session(engine) as session, session.begin():
                activities = list(session.scalars(select(Activity).order_by(Activity.id)))
                profiles = list(
                    session.scalars(select(AthleteProfile).order_by(AthleteProfile.effective_from))
                )
                calculated = skipped = 0
                present_ids = {activity.id for activity in activities}
                existing = {
                    item.activity_id: item for item in session.scalars(select(ActivityAnalytics))
                }
                for activity in activities:
                    annotation = session.get(ActivityAnnotation, activity.id)
                    profile = _profile_at(profiles, activity.local_date)
                    signature = _signature(activity, annotation, profile)
                    cached = existing.get(activity.id)
                    if (
                        cached is not None
                        and cached.input_signature == signature
                        and cached.algorithm_version == ANALYTICS_VERSION
                    ):
                        skipped += 1
                        continue
                    metrics = _activity_metrics(session, activity, annotation, profile)
                    session.merge(
                        ActivityAnalytics(
                            activity_id=activity.id,
                            input_signature=signature,
                            algorithm_version=ANALYTICS_VERSION,
                            metrics=metrics,
                        )
                    )
                    calculated += 1
                stale_ids = set(existing) - present_ids
                if stale_ids:
                    session.execute(
                        delete(ActivityAnalytics).where(
                            ActivityAnalytics.activity_id.in_(stale_ids)
                        )
                    )
                days = _daily_metrics(session, activities)
            return AnalysisReport(calculated, skipped, days)
        finally:
            engine.dispose()
