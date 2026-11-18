"""User-owned activity annotations."""

import math
from collections.abc import Callable

from sqlalchemy.orm import Session

from stridelog.config import Settings
from stridelog.db.engine import DATABASE_NAME, database_engine, initialize_database
from stridelog.db.models import Activity, ActivityAnnotation
from stridelog.errors import StridelogError
from stridelog.ingest.locking import sync_lock


def _update_annotation(
    settings: Settings,
    activity_id: int,
    update: Callable[[ActivityAnnotation], None],
) -> None:
    if activity_id <= 0:
        raise StridelogError("Activity ID must be positive.")
    if not (settings.data_dir / DATABASE_NAME).is_file():
        raise StridelogError("No local database; run sync and rebuild first.")
    with sync_lock(settings.data_dir):
        initialize_database(settings.data_dir)
        engine = database_engine(settings.data_dir)
        try:
            with Session(engine) as session, session.begin():
                if session.get(Activity, activity_id) is None:
                    raise StridelogError("Activity not found in the local database.")
                annotation = session.get(ActivityAnnotation, activity_id)
                if annotation is None:
                    annotation = ActivityAnnotation(activity_id=activity_id)
                update(annotation)
                session.add(annotation)
        finally:
            engine.dispose()


def set_steady_run(settings: Settings, activity_id: int, is_steady_run: bool) -> None:
    """Set an explicit steady-run annotation without exposing activity data."""
    _update_annotation(
        settings,
        activity_id,
        lambda annotation: setattr(annotation, "is_steady_run", is_steady_run),
    )


def set_race_details(
    settings: Settings,
    activity_id: int,
    *,
    is_race_override: bool | None,
    race_name: str | None,
    official_time_s: float | None,
    use_garmin: bool = False,
) -> None:
    """Set a race override and optional result without exposing personal values."""
    normalized_name = None if race_name is None else race_name.strip()
    if normalized_name == "":
        normalized_name = None
    if use_garmin and (
        is_race_override is not None or normalized_name is not None or official_time_s is not None
    ):
        raise StridelogError("--from-garmin cannot be combined with race overrides or details.")
    if official_time_s is not None and (not math.isfinite(official_time_s) or official_time_s <= 0):
        raise StridelogError("Official race time must be a positive finite number of seconds.")
    if (
        not use_garmin
        and is_race_override is False
        and (normalized_name is not None or official_time_s is not None)
    ):
        raise StridelogError("Race name and official time require a race override.")

    def update(annotation: ActivityAnnotation) -> None:
        annotation.is_race_override = None if use_garmin else is_race_override
        if use_garmin or is_race_override is False:
            annotation.race_name = None
            annotation.official_time_s = None
        else:
            if normalized_name is not None:
                annotation.race_name = normalized_name
            if official_time_s is not None:
                annotation.official_time_s = official_time_s

    _update_annotation(settings, activity_id, update)
