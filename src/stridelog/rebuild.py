"""Offline, transactional measurement rebuild from the checksummed raw manifest."""

import hashlib
import json
import zlib
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import date, datetime
from io import BytesIO
from pathlib import Path
from time import perf_counter
from zipfile import BadZipFile, ZipFile

from sqlalchemy import Engine, delete, insert, select
from sqlalchemy.orm import Session

from stridelog.config import Settings
from stridelog.db.engine import DATABASE_NAME, database_engine, database_status, initialize_database
from stridelog.db.models import (
    Activity,
    ActivityLap,
    ActivityRecord,
    ActivitySensor,
    Base,
    DailyWellness,
    HrvNight,
    QualityIssue,
    RawFile,
    SleepNight,
    TimerEvent,
    ZoneSnapshot,
)
from stridelog.errors import StridelogError
from stridelog.fit import (
    PARSER_VERSION,
    Event,
    FitError,
    Lap,
    Sample,
    Sensor,
    classify_hr,
    decode_fit,
)
from stridelog.ingest.archive import RawStore
from stridelog.ingest.locking import sync_lock
from stridelog.mapping import (
    MappingError,
    activity_metadata,
    numeric,
    object_fields,
    start_offset,
    wellness,
    zone_rows,
)
from stridelog.quality import activity_flags
from stridelog.storage import write_atomic

MEASUREMENTS: tuple[type[Base], ...] = (
    TimerEvent,
    ActivitySensor,
    ActivityLap,
    ActivityRecord,
    Activity,
    DailyWellness,
    SleepNight,
    HrvNight,
    ZoneSnapshot,
    QualityIssue,
)
MAX_FIT_BYTES = 128 * 1024 * 1024


@dataclass(frozen=True)
class RebuildReport:
    """Aggregate CLI output; private row identifiers stay in the local report."""

    imported_activities: int
    failed_activities: int
    failed_documents: int
    elapsed_s: float
    matches_previous: bool | None


def _json_date(value: object) -> str:
    if isinstance(value, date):
        return value.isoformat()
    raise TypeError("Unsupported report value")


def _serialize(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        ensure_ascii=True,
        allow_nan=False,
        default=_json_date,
    ).encode()


def _local_target(root: Path, relative: str) -> Path:
    target = root / relative
    if target.is_symlink() or not target.resolve().is_relative_to(root.resolve()):
        raise StridelogError("Linked report or quarantine target rejected.")
    return target


def _load_json(payload: bytes) -> object:
    try:
        result: object = json.loads(payload)
        return result
    except ValueError, UnicodeError:
        raise MappingError("json_decode") from None


def _read(store: RawStore, entry: RawFile) -> bytes:
    try:
        return store.read_verified(entry.relative_path)
    except StridelogError:
        raise MappingError("archive_integrity") from None


def _fit_member(payload: bytes) -> bytes:
    try:
        with ZipFile(BytesIO(payload)) as archive:
            members = [
                item for item in archive.infolist() if item.filename.lower().endswith(".fit")
            ]
            if len(members) != 1:
                raise FitError("ambiguous_fit_members")
            member = members[0]
            if member.file_size > MAX_FIT_BYTES:
                raise FitError("fit_size_limit")
            return archive.read(member)
    except BadZipFile, RuntimeError, zlib.error, NotImplementedError:
        raise FitError("zip_decode") from None


def _row(value: Sample | Lap | Sensor | Event) -> dict[str, object]:
    result: dict[str, object] = asdict(value)
    return {
        key: item.isoformat() if isinstance(item, datetime) else item
        for key, item in result.items()
    }


def _identifier(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, str | int):
        raise MappingError("activity_id_invalid")
    rendered = str(value)
    if not rendered.isascii() or not rendered.isdecimal() or not 0 < int(rendered) < 2**63:
        raise MappingError("activity_id_invalid")
    return int(rendered)


def _activity(
    settings: Settings,
    session: Session,
    store: RawStore,
    key: str,
    entries: list[RawFile],
) -> None:
    names = {entry.relative_path.rsplit("/", 1)[-1]: entry for entry in entries}
    if len(names) != len(entries) or set(names) != {"summary.json", "details.json", "original.zip"}:
        raise MappingError("incomplete_or_ambiguous_activity")
    identifier = _identifier(key)
    summary = object_fields(_load_json(_read(store, names["summary.json"])))
    details = object_fields(_load_json(_read(store, names["details.json"])))
    if _identifier(summary.get("activityId")) != identifier or (
        details.get("activityId") is not None and _identifier(details["activityId"]) != identifier
    ):
        raise MappingError("activity_id_mismatch")
    original = _read(store, names["original.zip"])
    try:
        parsed = decode_fit(_fit_member(original))
    except FitError:
        # Preserve the immutable archive; isolate a byte-identical copy for inspection.
        checksum = hashlib.sha256(original).hexdigest()
        write_atomic(
            _local_target(settings.data_dir, f"quarantine/{checksum}.zip"),
            original,
            immutable=True,
        )
        raise
    offset, local_day = start_offset(summary, parsed.start_time_utc)
    source, origin = classify_hr(parsed, local_day, settings.hr_armband_from)
    flags = activity_flags(
        parsed,
        numeric(summary, "distance"),
        summary_timer=numeric(summary, "duration"),
        summary_elapsed=numeric(summary, "elapsedDuration"),
    )
    if offset is None:
        flags.append("missing_start_offset")
    if source == "unknown":
        flags.append("unknown_hr_source")
    session.add(
        Activity(
            id=identifier,
            **activity_metadata(summary, details),
            start_time_utc=parsed.start_time_utc.isoformat(),
            utc_offset_s=offset,
            end_utc_offset_s=parsed.end_utc_offset_s,
            local_date=local_day,
            distance_m=parsed.distance_m,
            timer_time_s=parsed.timer_time_s,
            elapsed_time_s=parsed.elapsed_time_s,
            avg_hr_bpm=parsed.avg_hr_bpm,
            avg_cadence_spm=parsed.avg_cadence_spm,
            hr_source=source,
            hr_source_origin=origin,
            dq_flags=sorted(set(flags)),
            parser_version=PARSER_VERSION,
            source_checksums={entry.relative_path: entry.sha256 for entry in entries},
        )
    )
    session.flush()
    for model, index_name, values in (
        (ActivityRecord, "record_index", parsed.samples),
        (ActivityLap, "lap_index", parsed.laps),
        (ActivitySensor, "sensor_index", parsed.sensors),
        (TimerEvent, "event_index", parsed.events),
    ):
        if values:
            session.execute(
                insert(model),
                [
                    {"activity_id": identifier, index_name: index, **_row(value)}
                    for index, value in enumerate(values)
                ],
            )
    for flag in sorted(set(flags)):
        _issue(session, "activity_warning", key, flag)


def _issue(session: Session, dataset: str, key: str, code: str) -> None:
    session.merge(QualityIssue(dataset=dataset, source_key=key, code=code))


def _day(entry: RawFile) -> date:
    try:
        result = date.fromisoformat(entry.source_id or "")
        if result.isoformat() != entry.source_id:
            raise ValueError
        return result
    except ValueError:
        raise MappingError("wellness_date_invalid") from None


def _documents(session: Session, store: RawStore, entries: list[RawFile]) -> int:
    failures = 0
    zones_seen: set[tuple[str, str]] = set()
    for entry in entries:
        if entry.dataset not in {"daily", "sleep", "hrv", "zones"}:
            continue
        version = ".versions/" in entry.relative_path
        if entry.dataset != "zones" and version:
            continue
        try:
            payload = _load_json(_read(store, entry))
            if entry.dataset == "zones":
                for values in zone_rows(payload):
                    sport = str(values["sport"])
                    if (entry.sha256, sport) not in zones_seen:
                        session.add(
                            ZoneSnapshot(
                                raw_sha256=entry.sha256,
                                raw_path=entry.relative_path,
                                observed_at_utc=entry.updated_at_utc,
                                **values,
                            )
                        )
                        zones_seen.add((entry.sha256, sport))
            else:
                day = _day(entry)
                model = {"daily": DailyWellness, "sleep": SleepNight, "hrv": HrvNight}[
                    entry.dataset
                ]
                session.merge(
                    model(
                        local_date=day,
                        raw_path=entry.relative_path,
                        raw_sha256=entry.sha256,
                        **wellness(entry.dataset, payload, day),
                    )
                )
        except MappingError as error:
            failures += 1
            _issue(session, "document_failure", entry.relative_path, str(error))
    return failures


def _fingerprint(session: Session) -> str:
    digest = hashlib.sha256()
    for model in sorted(MEASUREMENTS, key=lambda item: item.__tablename__):
        table = model.__table__
        digest.update(model.__tablename__.encode())
        for row in session.execute(select(table).order_by(*table.primary_key)).mappings():
            digest.update(_serialize(dict(row)))
            digest.update(b"\n")
    return digest.hexdigest()


def _previous(root: Path) -> str | None:
    target = _local_target(root, "reports/rebuild.json")
    if not target.exists():
        return None
    previous = object_fields(_load_json(target.read_bytes())).get("fingerprint")
    if not isinstance(previous, str):
        raise StridelogError("Invalid previous rebuild report; inspect it locally.")
    return previous


def _rebuild(settings: Settings, session: Session) -> tuple[int, int, int]:
    entries = list(session.scalars(select(RawFile).order_by(RawFile.relative_path)))
    bundles: dict[str, list[RawFile]] = defaultdict(list)
    for entry in entries:
        if entry.dataset in {"activities", "originals"} and ".versions/" not in entry.relative_path:
            bundles[entry.source_id or ""].append(entry)
    if not entries:
        raise StridelogError("No archived activities found; finish sync before rebuilding.")
    for model in MEASUREMENTS:
        session.execute(delete(model))
    store = RawStore(settings.data_dir, session, "")
    failures = 0
    for key, bundle in sorted(bundles.items()):
        try:
            _activity(settings, session, store, key, bundle)
        except (FitError, MappingError) as error:
            failures += 1
            _issue(session, "activity_failure", key, str(error))
    failed_documents = _documents(session, store, entries)
    session.flush()
    return len(bundles) - failures, failures, failed_documents


def rebuild(settings: Settings) -> RebuildReport:
    """Replace only derived rows in one transaction; operational/user rows survive."""
    started = perf_counter()
    if not (settings.data_dir / DATABASE_NAME).is_file():
        raise StridelogError("No local archive database; finish sync before rebuilding.")
    with sync_lock(settings.data_dir):
        previous = _previous(settings.data_dir)
        initialize_database(settings.data_dir)
        engine = database_engine(settings.data_dir)
        try:
            with Session(engine) as session, session.begin():
                imported, failures, failed_documents = _rebuild(settings, session)
                fingerprint = _fingerprint(session)
            report = RebuildReport(
                imported,
                failures,
                failed_documents,
                perf_counter() - started,
                None if previous is None else previous == fingerprint,
            )
            write_atomic(
                _local_target(settings.data_dir, "reports/rebuild.json"),
                _serialize(asdict(report) | {"fingerprint": fingerprint}),
                immutable=False,
            )
            _write_quality(settings.data_dir, engine)
            return report
        finally:
            engine.dispose()


def _write_quality(root: Path, engine: Engine) -> int:
    with Session(engine) as session:
        issues = [
            {"dataset": item.dataset, "source_key": item.source_key, "code": item.code}
            for item in session.scalars(
                select(QualityIssue).order_by(
                    QualityIssue.dataset,
                    QualityIssue.source_key,
                    QualityIssue.code,
                )
            )
        ]
        activities: list[dict[str, object]] = [
            {"activity_id": item.id, "status": "imported", "flags": item.dq_flags}
            for item in session.scalars(select(Activity).order_by(Activity.id))
        ]
    activities.extend(
        {"source_key": item["source_key"], "status": "failed", "code": item["code"]}
        for item in issues
        if item["dataset"] == "activity_failure"
    )
    write_atomic(
        _local_target(root, "reports/data-quality.json"),
        _serialize({"parser_version": PARSER_VERSION, "activities": activities, "issues": issues}),
        immutable=False,
    )
    return len(issues)


def quality_report(settings: Settings) -> int:
    """Write private stored findings, without reparsing, network or value logging."""
    if not (settings.data_dir / DATABASE_NAME).is_file():
        raise StridelogError("No database; finish sync and rebuild first.")
    with sync_lock(settings.data_dir):
        database_status(settings.data_dir)
        if _previous(settings.data_dir) is None:
            raise StridelogError("No completed rebuild; run rebuild first.")
        engine = database_engine(settings.data_dir)
        try:
            return _write_quality(settings.data_dir, engine)
        finally:
            engine.dispose()
