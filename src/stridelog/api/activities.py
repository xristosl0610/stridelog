"""Activity and route endpoints."""

import math
from datetime import date
from typing import Annotated, cast

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from stridelog.activity_annotations import (
    update_activity_annotation as save_annotation,
)
from stridelog.analysis import analyze as run_analysis
from stridelog.analytics import ANALYTICS_VERSION
from stridelog.api.dependencies import get_session
from stridelog.api.schemas import (
    ActivityDetail,
    ActivityPage,
    ActivitySummary,
    AnnotationUpdate,
    GeoJsonFeature,
    GeoJsonFeatureCollection,
    GeoJsonGeometry,
    StreamPoint,
    StreamResponse,
)
from stridelog.db.models import (
    Activity,
    ActivityAnalytics,
    ActivityAnnotation,
    ActivityRecord,
)
from stridelog.errors import AnnotationValidationError

router = APIRouter(prefix="/api/v1")
SessionDependency = Annotated[Session, Depends(get_session)]


def _summary(activity: Activity, annotation: ActivityAnnotation | None) -> ActivitySummary:
    effective_race = (
        activity.is_race
        if annotation is None or annotation.is_race_override is None
        else annotation.is_race_override
    )
    return ActivitySummary(
        id=activity.id,
        name=activity.name,
        activity_type=activity.activity_type,
        is_race=effective_race,
        start_time_utc=activity.start_time_utc,
        utc_offset_s=activity.utc_offset_s,
        local_date=activity.local_date,
        distance_m=activity.distance_m,
        timer_time_s=activity.timer_time_s,
        elapsed_time_s=activity.elapsed_time_s,
        avg_hr_bpm=activity.avg_hr_bpm,
        avg_cadence_spm=activity.avg_cadence_spm,
        hr_source=activity.hr_source,
        dq_flags=activity.dq_flags,
        is_race_override=None if annotation is None else annotation.is_race_override,
        race_name=None if annotation is None else annotation.race_name,
        official_time_s=None if annotation is None else annotation.official_time_s,
        notes=None if annotation is None else annotation.notes,
        excluded_from_stats=annotation is not None and annotation.exclude_from_stats,
    )


def _activity_or_404(session: Session, activity_id: int) -> Activity:
    activity = session.get(Activity, activity_id)
    if activity is None:
        raise HTTPException(status_code=404, detail="Activity not found.")
    return activity


def _current_metrics(cached: ActivityAnalytics | None) -> dict[str, object]:
    if cached is None or cached.algorithm_version != ANALYTICS_VERSION:
        return {}
    return cached.metrics


@router.get("/activities", response_model=ActivityPage)
def list_activities(
    session: SessionDependency,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 25,
    search: Annotated[str | None, Query(max_length=200)] = None,
    activity_type: Annotated[str | None, Query(max_length=100)] = None,
    start_date: date | None = None,
    end_date: date | None = None,
    race: bool | None = None,
    include_excluded: bool = False,
) -> ActivityPage:
    if start_date is not None and end_date is not None and start_date > end_date:
        raise HTTPException(status_code=422, detail="start_date must not be after end_date.")

    effective_race = case(
        (ActivityAnnotation.is_race_override.is_not(None), ActivityAnnotation.is_race_override),
        else_=Activity.is_race,
    )
    statement = select(Activity, ActivityAnnotation).outerjoin(
        ActivityAnnotation, ActivityAnnotation.activity_id == Activity.id
    )
    filters: list[ColumnElement[bool]] = []
    if not include_excluded:
        filters.append(ActivityAnnotation.exclude_from_stats.is_not(True))
    if activity_type is not None:
        filters.append(Activity.activity_type == activity_type)
    if start_date is not None:
        filters.append(Activity.local_date >= start_date)
    if end_date is not None:
        filters.append(Activity.local_date <= end_date)
    if race is not None:
        filters.append(effective_race == race)
    if search is not None:
        filters.append(Activity.name.ilike(f"%{search}%"))
    if filters:
        statement = statement.where(*filters)

    total = session.scalar(select(func.count()).select_from(statement.subquery())) or 0
    rows = session.execute(
        statement.order_by(Activity.start_time_utc.desc(), Activity.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return ActivityPage(
        items=[_summary(activity, annotation) for activity, annotation in rows],
        page=page,
        page_size=page_size,
        total=total,
    )


@router.get("/activities/{activity_id}", response_model=ActivityDetail)
def activity_detail(activity_id: int, session: SessionDependency) -> ActivityDetail:
    activity = _activity_or_404(session, activity_id)
    annotation = session.get(ActivityAnnotation, activity_id)
    cached = session.get(ActivityAnalytics, activity_id)
    return ActivityDetail(
        **_summary(activity, annotation).model_dump(),
        metrics=_current_metrics(cached),
    )


@router.get("/activities/{activity_id}/streams", response_model=StreamResponse)
def activity_stream(
    activity_id: int,
    session: SessionDependency,
    full_resolution: bool = False,
    max_points: Annotated[int, Query(ge=2, le=10_000)] = 1_000,
) -> StreamResponse:
    _activity_or_404(session, activity_id)
    records = list(
        session.scalars(
            select(ActivityRecord)
            .where(ActivityRecord.activity_id == activity_id)
            .order_by(ActivityRecord.record_index)
        )
    )
    if not full_resolution and len(records) > max_points:
        stride = math.ceil((len(records) - 1) / (max_points - 1))
        selected = records[::stride]
        if selected[-1] is not records[-1]:
            selected.append(records[-1])
        records = selected
    return StreamResponse(
        activity_id=activity_id,
        full_resolution=full_resolution,
        points=[
            StreamPoint(
                record_index=record.record_index,
                ts_utc=record.ts_utc,
                distance_m=record.distance_m,
                lat_deg=record.lat_deg,
                lon_deg=record.lon_deg,
                altitude_m=record.altitude_m,
                speed_mps=record.speed_mps,
                heart_rate_bpm=record.heart_rate_bpm,
                cadence_spm=record.cadence_spm,
            )
            for record in records
        ],
    )


@router.get("/activities/{activity_id}/route", response_model=GeoJsonFeatureCollection)
def activity_route(activity_id: int, session: SessionDependency) -> GeoJsonFeatureCollection:
    _activity_or_404(session, activity_id)
    coordinates: list[tuple[float, float]] = []
    for record in session.scalars(
        select(ActivityRecord)
        .where(ActivityRecord.activity_id == activity_id)
        .order_by(ActivityRecord.record_index)
    ):
        if (
            record.lat_deg is not None
            and record.lon_deg is not None
            and math.isfinite(record.lat_deg)
            and math.isfinite(record.lon_deg)
            and -90 <= record.lat_deg <= 90
            and -180 <= record.lon_deg <= 180
        ):
            coordinates.append((record.lon_deg, record.lat_deg))
    if len(coordinates) < 2:
        raise HTTPException(status_code=404, detail="Activity route is unavailable.")
    return GeoJsonFeatureCollection(
        type="FeatureCollection",
        features=[
            GeoJsonFeature(
                type="Feature",
                geometry=GeoJsonGeometry(
                    type="LineString",
                    coordinates=coordinates,
                ),
                properties={"activity_id": activity_id},
            )
        ],
    )


@router.patch("/activities/{activity_id}/annotation", response_model=ActivitySummary)
def update_activity_annotation(
    activity_id: int,
    update: AnnotationUpdate,
    session: SessionDependency,
    request: Request,
) -> ActivitySummary:
    _activity_or_404(session, activity_id)
    changes = update.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(status_code=422, detail="At least one annotation field is required.")
    settings = request.app.state.settings
    try:
        save_annotation(settings, activity_id, changes)
    except AnnotationValidationError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    run_analysis(settings)
    session.rollback()
    activity = _activity_or_404(session, activity_id)
    annotation = session.get(ActivityAnnotation, activity_id)
    return _summary(activity, annotation)


def get_metric_list(value: object, key: str) -> list[dict[str, object]]:
    """Read a cached list without accepting unexpected JSON shapes."""
    if not isinstance(value, dict):
        return []
    mapping = cast("dict[str, object]", value)
    items = mapping.get(key)
    if not isinstance(items, list):
        return []
    values = cast("list[object]", items)
    return [cast("dict[str, object]", item) for item in values if isinstance(item, dict)]


__all__ = ["_current_metrics", "_summary", "get_metric_list", "router"]
