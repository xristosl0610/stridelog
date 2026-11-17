"""Incremental raw synchronization; no health metrics or FIT decoding."""

from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import date, timedelta

from pydantic import JsonValue
from sqlalchemy import Engine, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from stridelog.config import Settings
from stridelog.db.engine import database_engine, initialize_database
from stridelog.db.models import SyncCursor, SyncRun, utc_now
from stridelog.errors import StridelogError
from stridelog.garmin import GarminSource
from stridelog.ingest.archive import RawStore
from stridelog.ingest.locking import sync_lock

BASELINE = date(2025, 1, 1)


@dataclass
class SyncReport:
    """Aggregate counters only; counts exclude immutable JSON version copies."""

    updated_documents: int = 0
    downloaded_originals: int = 0


def _object(value: JsonValue) -> dict[str, JsonValue]:
    if not isinstance(value, dict):
        raise StridelogError(
            "Unexpected Garmin object shape; sync stopped without advancing progress."
        )
    return value


def _identifier(value: JsonValue) -> str:
    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
        return str(value)
    if isinstance(value, str) and value.isascii() and value.isdecimal() and value.strip("0"):
        return value.lstrip("0")
    raise StridelogError("Invalid Garmin activity identifier.")


def _running_keys(catalog: JsonValue, configured: tuple[str, ...]) -> set[str]:
    if not isinstance(catalog, list) or not catalog:
        raise StridelogError("Activity taxonomy is unavailable; no activities selected.")
    parents: dict[str, str | None] = {}
    for item in catalog:
        entry = _object(item)
        key, parent = entry.get("key"), entry.get("parent")
        if isinstance(parent, dict):
            parent = parent.get("key")
            if not isinstance(parent, str) or not parent:
                raise StridelogError("Unexpected activity taxonomy parent reference.")
        if (
            not isinstance(key, str)
            or not key
            or (parent is not None and not isinstance(parent, str))
        ):
            raise StridelogError("Unexpected activity taxonomy shape.")
        if key in parents and parents[key] != parent:
            raise StridelogError("Conflicting activity taxonomy parents.")
        parents[key] = parent
    selected = set(configured)
    while children := {key for key, parent in parents.items() if parent in selected} - selected:
        selected.update(children)
    return selected


def _start(engine: Engine, dataset: str, since: date | None, lookback: int) -> date:
    if since is not None:
        return since
    with Session(engine) as session:
        cursor = session.get(SyncCursor, dataset)
        if cursor is None:
            return BASELINE
        return _lookback_start(cursor.through_date, lookback)


def _lookback_start(through: date, lookback: int) -> date:
    try:
        return max(BASELINE, through - timedelta(days=lookback))
    except OverflowError:
        raise StridelogError("Lookback exceeds the supported calendar range.") from None


def _advance(session: Session, dataset: str, through: date) -> None:
    cursor = session.get(SyncCursor, dataset)
    if cursor is None:
        session.add(SyncCursor(dataset=dataset, through_date=through))
    elif through > cursor.through_date:
        cursor.through_date = through


def _activity_day(summary: dict[str, JsonValue], start: date, end: date) -> date:
    value = summary.get("startTimeLocal")
    try:
        if not isinstance(value, str):
            raise ValueError
        day = date.fromisoformat(value[:10])
        if value[:10] != day.isoformat() or not start <= day <= end:
            raise ValueError
        return day
    except ValueError:
        raise StridelogError(
            "Activity local date is invalid or outside the requested range."
        ) from None


def _archive_activity(
    source: GarminSource,
    store: RawStore,
    summary: dict[str, JsonValue],
    identifier: str,
    day: date,
    refresh: bool,
    report: SyncReport,
) -> None:
    prefix = f"raw/activities/{day.year}/{identifier}"
    changed = store.write_json(f"{prefix}/summary.json", summary, "activities", identifier)
    report.updated_documents += changed
    if changed or refresh or not store.has(f"{prefix}/details.json"):
        details = _object(source.details(identifier))
        if "activityId" in details and _identifier(details["activityId"]) != identifier:
            raise StridelogError("Activity details identifier does not match the request.")
        report.updated_documents += store.write_json(
            f"{prefix}/details.json", details, "activities", identifier
        )
    if not store.has_original(f"{prefix}/original.zip", identifier):
        store.write_original(f"{prefix}/original.zip", source.original(identifier), identifier)
        report.downloaded_originals += 1


def _activities(
    settings: Settings,
    engine: Engine,
    source: GarminSource,
    run_id: str,
    since: date | None,
    today: date,
    report: SyncReport,
) -> None:
    catalog = source.activity_types()
    selected = _running_keys(catalog, settings.running_activity_types)
    with Session(engine) as session, session.begin():
        report.updated_documents += RawStore(settings.data_dir, session, run_id).write_json(
            "raw/profile/activity-types.json", catalog, "activity_types", "current"
        )
    start = _start(engine, "activities", since, settings.activity_lookback_days)
    offset = 0
    seen: set[str] = set()
    while True:
        page = source.activities(start, today, offset)
        if not isinstance(page, list) or len(page) > 20:
            raise StridelogError("Unexpected activity page shape.")
        if not page:
            break
        for item in page:
            summary = _object(item)
            identifier = _identifier(summary.get("activityId"))
            if identifier in seen:
                raise StridelogError("Activity paging changed; retry sync to reconcile safely.")
            seen.add(identifier)
            activity_type = _object(summary.get("activityType")).get("typeKey")
            if not isinstance(activity_type, str):
                raise StridelogError("Activity type key is missing.")
            if activity_type not in selected:
                continue
            day = _activity_day(summary, start, today)
            with Session(engine) as session, session.begin():
                store = RawStore(settings.data_dir, session, run_id)
                refresh = since is not None or day >= _lookback_start(
                    today, settings.activity_lookback_days
                )
                _archive_activity(source, store, summary, identifier, day, refresh, report)
        offset += len(page)
    with Session(engine) as session, session.begin():
        _advance(session, "activities", today)


def _wellness(
    settings: Settings,
    engine: Engine,
    source: GarminSource,
    run_id: str,
    since: date | None,
    today: date,
    report: SyncReport,
) -> None:
    for dataset in ("daily", "sleep", "hrv"):
        day = _start(engine, dataset, since, settings.wellness_lookback_days)
        while day <= today:
            payload = source.wellness(dataset, day)
            if payload is not None and not isinstance(payload, dict | list):
                raise StridelogError("Unexpected wellness response shape.")
            with Session(engine) as session, session.begin():
                store = RawStore(settings.data_dir, session, run_id)
                report.updated_documents += store.write_json(
                    f"raw/wellness/{dataset}/{day.isoformat()}_{day.isoformat()}.json",
                    payload,
                    dataset,
                    day.isoformat(),
                )
                _advance(session, dataset, day)
            day += timedelta(days=1)


def _begin_run(engine: Engine) -> str:
    with Session(engine) as session, session.begin():
        session.execute(
            update(SyncRun)
            .where(SyncRun.status == "running")
            .values(status="failed", error_code="interrupted", finished_at_utc=utc_now())
        )
        run = SyncRun()
        session.add(run)
        session.flush()
        return run.id


def _finish_run(engine: Engine, run_id: str, error_code: str | None) -> None:
    with Session(engine) as session, session.begin():
        session.execute(
            update(SyncRun)
            .where(SyncRun.id == run_id)
            .values(
                status="failed" if error_code else "succeeded",
                error_code=error_code,
                finished_at_utc=utc_now(),
            )
        )


def synchronize(
    settings: Settings,
    source_factory: Callable[[], AbstractContextManager[GarminSource]],
    *,
    since: date | None = None,
    today: date | None = None,
) -> SyncReport:
    """Archive durably under a process lock, then advance per-dataset progress."""
    end = today or date.today()
    if since is not None and since > end:
        raise StridelogError("--since must not be in the future.")
    if settings.api_key_expires_on is not None and settings.api_key_expires_on < end:
        raise StridelogError("Configured API key is expired; renew it before syncing.")
    report = SyncReport()
    with sync_lock(settings.data_dir):
        initialize_database(settings.data_dir)
        engine = database_engine(settings.data_dir)
        try:
            run_id = _begin_run(engine)
            try:
                with source_factory() as source:
                    _activities(settings, engine, source, run_id, since, end, report)
                    _wellness(settings, engine, source, run_id, since, end, report)
                    with Session(engine) as session, session.begin():
                        report.updated_documents += RawStore(
                            settings.data_dir, session, run_id
                        ).write_json(
                            "raw/profile/heart-rate-zones/current.json",
                            source.zones(),
                            "zones",
                            "current",
                        )
            except (StridelogError, SQLAlchemyError, OSError, KeyboardInterrupt) as error:
                code = (
                    "interrupted" if isinstance(error, KeyboardInterrupt) else "source_or_storage"
                )
                _finish_run(engine, run_id, code)
                raise
            _finish_run(engine, run_id, None)
        finally:
            engine.dispose()
    return report
