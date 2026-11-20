"""User-owned activity annotations."""

import math
from collections.abc import Callable

from sqlalchemy.orm import Session

from stridelog.config import Settings
from stridelog.db.engine import DATABASE_NAME, database_engine, initialize_database
from stridelog.db.models import Activity, ActivityAnnotation
from stridelog.errors import AnnotationValidationError, StridelogError
from stridelog.ingest.locking import sync_lock


def _update_annotation(
    settings: Settings,
    activity_id: int,
    update: Callable[[Activity, ActivityAnnotation], None],
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
                activity = session.get(Activity, activity_id)
                if activity is None:
                    raise StridelogError("Activity not found in the local database.")
                annotation = session.get(ActivityAnnotation, activity_id)
                if annotation is None:
                    annotation = ActivityAnnotation(activity_id=activity_id)
                update(activity, annotation)
                session.add(annotation)
        finally:
            engine.dispose()


def set_steady_run(settings: Settings, activity_id: int, is_steady_run: bool) -> None:
    """Set an explicit steady-run annotation without exposing activity data."""
    _update_annotation(
        settings,
        activity_id,
        lambda _activity, annotation: setattr(annotation, "is_steady_run", is_steady_run),
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

    def update(_activity: Activity, annotation: ActivityAnnotation) -> None:
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


def update_activity_annotation(
    settings: Settings, activity_id: int, updates: dict[str, object]
) -> None:
    """Apply validated API annotation fields while holding the shared sync lock."""
    allowed = {
        "is_race_override",
        "race_name",
        "official_time_s",
        "notes",
        "exclude_from_stats",
    }
    if not updates or not set(updates).issubset(allowed):
        raise AnnotationValidationError("Annotation update fields are invalid.")

    def update(activity: Activity, annotation: ActivityAnnotation) -> None:
        has_override = "is_race_override" in updates
        override = updates.get("is_race_override")
        if has_override and override is not None and not isinstance(override, bool):
            raise AnnotationValidationError("Race override must be a boolean or null.")

        has_name = "race_name" in updates
        name = updates.get("race_name")
        if has_name and name is not None and not isinstance(name, str):
            raise AnnotationValidationError("Race name must be text or null.")
        normalized_name = (name.strip() or None) if isinstance(name, str) else None

        has_official_time = "official_time_s" in updates
        official_time = updates.get("official_time_s")
        official_time_s: float | None = None
        if has_official_time and official_time is not None:
            if not isinstance(official_time, int | float) or isinstance(official_time, bool):
                raise AnnotationValidationError("Official race time must be positive and finite.")
            if not math.isfinite(official_time) or official_time <= 0:
                raise AnnotationValidationError("Official race time must be positive and finite.")
            official_time_s = float(official_time)

        if has_override:
            if override is None:
                effective_race = activity.is_race
            elif isinstance(override, bool):
                effective_race = override
            else:
                raise AnnotationValidationError("Race override must be a boolean or null.")
        else:
            effective_race = (
                activity.is_race
                if annotation.is_race_override is None
                else annotation.is_race_override
            )
        if effective_race is not True and (
            (has_name and normalized_name is not None) or official_time_s is not None
        ):
            raise AnnotationValidationError("Race details require an activity marked as a race.")

        if has_override:
            if override is None:
                annotation.is_race_override = None
            elif isinstance(override, bool):
                annotation.is_race_override = override
            else:
                raise AnnotationValidationError("Race override must be a boolean or null.")
            if override is not True:
                annotation.race_name = None
                annotation.official_time_s = None
        if has_name:
            annotation.race_name = normalized_name
        if has_official_time:
            annotation.official_time_s = official_time_s

        if "notes" in updates:
            notes = updates["notes"]
            if notes is not None and not isinstance(notes, str):
                raise AnnotationValidationError("Activity notes must be text or null.")
            annotation.notes = notes

        if "exclude_from_stats" in updates:
            excluded = updates["exclude_from_stats"]
            if excluded is not None and not isinstance(excluded, bool):
                raise AnnotationValidationError("Activity exclusion must be a boolean or null.")
            annotation.exclude_from_stats = excluded is True

    _update_annotation(settings, activity_id, update)
