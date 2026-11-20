"""Trend, race and wellness read endpoints."""

from collections import defaultdict
from datetime import date
from typing import Annotated, Literal, cast

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import case, select
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from stridelog.api.activities import _current_metrics, _summary, get_metric_list
from stridelog.api.dependencies import get_session
from stridelog.api.schemas import (
    BestEffortEntry,
    DailyMetrics,
    PredictionEntry,
    RaceEntry,
    TrendPoint,
    VolumePoint,
    WellnessDay,
)
from stridelog.db.models import (
    Activity,
    ActivityAnalytics,
    ActivityAnnotation,
    DailyAnalytics,
    DailyWellness,
    HrvNight,
    SleepNight,
)

router = APIRouter(prefix="/api/v1")
SessionDependency = Annotated[Session, Depends(get_session)]


def _period_start(day: date, period: Literal["week", "month", "year"]) -> date:
    if period == "week":
        return date.fromordinal(day.toordinal() - day.weekday())
    if period == "month":
        return day.replace(day=1)
    return day.replace(month=1, day=1)


def _effective_race_filter() -> ColumnElement[bool]:
    return case(
        (ActivityAnnotation.is_race_override.is_not(None), ActivityAnnotation.is_race_override),
        else_=Activity.is_race,
    )


@router.get("/trends/volume", response_model=list[VolumePoint])
def volume_trends(
    session: SessionDependency,
    period: Literal["week", "month", "year"] = "week",
    start_date: date | None = None,
    end_date: date | None = None,
) -> list[VolumePoint]:
    if start_date is not None and end_date is not None and start_date > end_date:
        raise HTTPException(status_code=422, detail="start_date must not be after end_date.")
    rows = session.execute(
        select(Activity, ActivityAnnotation)
        .outerjoin(ActivityAnnotation, ActivityAnnotation.activity_id == Activity.id)
        .where(Activity.local_date.is_not(None))
        .order_by(Activity.local_date)
    ).all()
    totals: dict[date, list[float]] = defaultdict(lambda: [0.0, 0.0, 0.0])
    for activity, annotation_row in rows:
        annotation = cast("ActivityAnnotation | None", annotation_row)
        day = activity.local_date
        if (
            day is None
            or (start_date is not None and day < start_date)
            or (end_date is not None and day > end_date)
            or (annotation is not None and annotation.exclude_from_stats)
        ):
            continue
        start = _period_start(day, period)
        totals[start][0] += activity.distance_m or 0.0
        totals[start][1] += activity.timer_time_s or 0.0
        totals[start][2] += 1
    return [
        VolumePoint(
            period_start=period_start,
            distance_m=values[0],
            duration_s=values[1],
            activity_count=int(values[2]),
        )
        for period_start, values in sorted(totals.items())
    ]


@router.get("/trends", response_model=list[TrendPoint])
def activity_trends(
    session: SessionDependency,
    start_date: date | None = None,
    end_date: date | None = None,
) -> list[TrendPoint]:
    if start_date is not None and end_date is not None and start_date > end_date:
        raise HTTPException(status_code=422, detail="start_date must not be after end_date.")
    rows = session.execute(
        select(Activity, ActivityAnnotation, ActivityAnalytics)
        .outerjoin(ActivityAnnotation, ActivityAnnotation.activity_id == Activity.id)
        .outerjoin(ActivityAnalytics, ActivityAnalytics.activity_id == Activity.id)
        .where(Activity.local_date.is_not(None))
        .order_by(Activity.local_date, Activity.id)
    ).all()
    result: list[TrendPoint] = []
    for activity, annotation_row, cached_row in rows:
        annotation = cast("ActivityAnnotation | None", annotation_row)
        cached = cast("ActivityAnalytics | None", cached_row)
        if (
            activity.local_date is None
            or (start_date is not None and activity.local_date < start_date)
            or (end_date is not None and activity.local_date > end_date)
            or (annotation is not None and annotation.exclude_from_stats)
        ):
            continue
        invalid_hr = annotation is not None and annotation.hr_invalid
        distance = activity.distance_m
        timer = activity.timer_time_s
        metrics = _current_metrics(cached)
        efficiency = metrics.get("efficiency_factor")
        result.append(
            TrendPoint(
                activity_id=activity.id,
                local_date=activity.local_date,
                distance_m=distance,
                pace_s_per_km=(
                    None
                    if distance is None or distance <= 0 or timer is None
                    else timer / distance * 1_000
                ),
                avg_hr_bpm=None if invalid_hr else activity.avg_hr_bpm,
                avg_cadence_spm=activity.avg_cadence_spm,
                efficiency_factor=(
                    None
                    if invalid_hr
                    or not isinstance(efficiency, int | float)
                    or isinstance(efficiency, bool)
                    else float(efficiency)
                ),
            )
        )
    return result


@router.get("/best-efforts", response_model=list[BestEffortEntry])
def best_efforts(
    session: SessionDependency,
    distance_m: Annotated[float | None, Query(gt=0)] = None,
) -> list[BestEffortEntry]:
    rows = session.execute(
        select(Activity, ActivityAnalytics, ActivityAnnotation)
        .join(ActivityAnalytics, ActivityAnalytics.activity_id == Activity.id)
        .outerjoin(ActivityAnnotation, ActivityAnnotation.activity_id == Activity.id)
        .where(ActivityAnnotation.exclude_from_stats.is_not(True))
        .order_by(Activity.local_date.desc(), Activity.id.desc())
    ).all()
    entries: list[BestEffortEntry] = []
    for activity, cached_row, _annotation in rows:
        for effort in get_metric_list(_current_metrics(cached_row), "best_efforts"):
            effort_distance = effort.get("distance_m")
            effort_duration = effort.get("duration_s")
            if (
                not isinstance(effort_distance, int | float)
                or isinstance(effort_distance, bool)
                or not isinstance(effort_duration, int | float)
                or isinstance(effort_duration, bool)
                or (distance_m is not None and effort_distance != distance_m)
            ):
                continue
            entries.append(
                BestEffortEntry(
                    activity_id=activity.id,
                    local_date=activity.local_date,
                    name=activity.name,
                    distance_m=float(effort_distance),
                    duration_s=float(effort_duration),
                )
            )
    return sorted(entries, key=lambda item: (item.duration_s, item.distance_m))


@router.get("/races", response_model=list[RaceEntry])
def races(session: SessionDependency) -> list[RaceEntry]:
    rows = session.execute(
        select(Activity, ActivityAnnotation, ActivityAnalytics)
        .outerjoin(ActivityAnnotation, ActivityAnnotation.activity_id == Activity.id)
        .outerjoin(ActivityAnalytics, ActivityAnalytics.activity_id == Activity.id)
        .where(_effective_race_filter().is_(True))
        .order_by(Activity.local_date.desc(), Activity.id.desc())
    ).all()
    result: list[RaceEntry] = []
    for activity, annotation_row, cached_row in rows:
        annotation = cast("ActivityAnnotation | None", annotation_row)
        cached = cast("ActivityAnalytics | None", cached_row)
        metrics = _current_metrics(cached)
        result.append(
            RaceEntry(
                activity=_summary(activity, annotation),
                official_time_s=(None if annotation is None else annotation.official_time_s),
                predictions=get_metric_list(metrics, "race_predictions"),
            )
        )
    return result


@router.get("/training-load", response_model=list[DailyMetrics])
def training_load(
    session: SessionDependency,
    start_date: date | None = None,
    end_date: date | None = None,
) -> list[DailyMetrics]:
    if start_date is not None and end_date is not None and start_date > end_date:
        raise HTTPException(status_code=422, detail="start_date must not be after end_date.")
    statement = select(DailyAnalytics).order_by(DailyAnalytics.local_date)
    if start_date is not None:
        statement = statement.where(DailyAnalytics.local_date >= start_date)
    if end_date is not None:
        statement = statement.where(DailyAnalytics.local_date <= end_date)
    return [
        DailyMetrics(local_date=row.local_date, metrics=row.metrics)
        for row in session.scalars(statement)
    ]


@router.get("/wellness", response_model=list[WellnessDay])
def wellness(
    session: SessionDependency,
    start_date: date | None = None,
    end_date: date | None = None,
) -> list[WellnessDay]:
    if start_date is not None and end_date is not None and start_date > end_date:
        raise HTTPException(status_code=422, detail="start_date must not be after end_date.")
    wellness_rows = {row.local_date: row for row in session.scalars(select(DailyWellness))}
    sleep_rows = {row.local_date: row for row in session.scalars(select(SleepNight))}
    hrv_rows = {row.local_date: row for row in session.scalars(select(HrvNight))}
    days = sorted(set(wellness_rows) | set(sleep_rows) | set(hrv_rows))
    return [
        WellnessDay(
            local_date=day,
            resting_hr_bpm=(
                None if day not in wellness_rows else wellness_rows[day].resting_hr_bpm
            ),
            steps=None if day not in wellness_rows else wellness_rows[day].steps,
            stress_avg=None if day not in wellness_rows else wellness_rows[day].stress_avg,
            body_battery_high=(
                None if day not in wellness_rows else wellness_rows[day].body_battery_high
            ),
            body_battery_low=(
                None if day not in wellness_rows else wellness_rows[day].body_battery_low
            ),
            sleep_duration_s=None if day not in sleep_rows else sleep_rows[day].duration_s,
            sleep_score=None if day not in sleep_rows else sleep_rows[day].score,
            hrv_ms=None if day not in hrv_rows else hrv_rows[day].last_night_avg_ms,
        )
        for day in days
        if (start_date is None or day >= start_date) and (end_date is None or day <= end_date)
    ]


@router.get("/predictions", response_model=list[PredictionEntry])
def predictions(session: SessionDependency) -> list[PredictionEntry]:
    rows = session.execute(
        select(Activity, ActivityAnnotation, ActivityAnalytics)
        .join(ActivityAnalytics, ActivityAnalytics.activity_id == Activity.id)
        .outerjoin(ActivityAnnotation, ActivityAnnotation.activity_id == Activity.id)
        .where(_effective_race_filter().is_(True))
        .order_by(Activity.local_date.desc(), Activity.id.desc())
    ).all()
    return [
        PredictionEntry(
            activity_id=activity.id,
            local_date=activity.local_date,
            name=activity.name,
            predictions=get_metric_list(_current_metrics(cached), "race_predictions"),
        )
        for activity, _annotation, cached in rows
        if get_metric_list(_current_metrics(cached), "race_predictions")
    ]


__all__ = ["router"]
