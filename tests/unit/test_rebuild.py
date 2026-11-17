"""Offline rebuild acceptance using only invented JSON and SDK-encoded FIT."""

import hashlib
import json
from dataclasses import replace
from datetime import date, timedelta
from io import BytesIO
from zipfile import ZipFile, ZipInfo

import pytest
from pydantic import JsonValue
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from typer.testing import CliRunner

from stridelog.cli import app
from stridelog.config import Settings
from stridelog.db.engine import database_engine, initialize_database
from stridelog.db.models import (
    Activity,
    ActivityAnnotation,
    ActivityRecord,
    DailyWellness,
    HrvNight,
    QualityIssue,
    RawFile,
    SleepNight,
    SyncCursor,
    SyncRun,
    ZoneSnapshot,
)
from stridelog.errors import StridelogError
from stridelog.fit import decode_fit
from stridelog.ingest.archive import RawStore
from stridelog.ingest.locking import sync_lock
from stridelog.mapping import MappingError, start_offset, wellness, zone_rows
from stridelog.quality import activity_flags
from stridelog.rebuild import quality_report, rebuild
from stridelog.synthetic import running_fit

pytestmark = pytest.mark.usefixtures("private_environment")
DAY = date(2030, 3, 31)
runner = CliRunner()


def _zip(payload: bytes) -> bytes:
    buffer = BytesIO()
    with ZipFile(buffer, "w") as archive:
        archive.writestr(ZipInfo("synthetic.fit", date_time=(2030, 3, 31, 0, 0, 0)), payload)
    return buffer.getvalue()


def _seed(*, bad_second: bool = False) -> Settings:
    settings = Settings()
    initialize_database(settings.data_dir)
    engine = database_engine(settings.data_dir)
    try:
        with Session(engine) as session, session.begin():
            session.add(SyncRun(id="synthetic", status="succeeded"))
            session.flush()
            session.add(SyncCursor(dataset="activities", through_date=DAY))
            store = RawStore(settings.data_dir, session, "synthetic")
            for identifier in ("1", "2"):
                prefix = f"raw/activities/2030/{identifier}"
                summary: dict[str, JsonValue] = {
                    "activityId": identifier,
                    "activityName": "Synthetic private title",
                    "startTimeGMT": "2030-03-31 00:59:58",
                    "startTimeLocal": "2030-03-31 01:59:58",
                    "activityType": {"typeKey": "running"},
                    "distance": 18,
                }
                store.write_json(f"{prefix}/summary.json", summary, "activities", identifier)
                store.write_json(
                    f"{prefix}/details.json",
                    {"activityId": identifier, "eventTypeDTO": {"typeKey": "race"}},
                    "activities",
                    identifier,
                )
                payload = (
                    b"corrupt synthetic FIT"
                    if bad_second and identifier == "2"
                    else running_fit(
                        gps=identifier == "1",
                        paused=True,
                        dropout=True,
                        offset_s=7200,
                    )
                )
                store.write_original(f"{prefix}/original.zip", _zip(payload), identifier)
            documents: tuple[tuple[str, JsonValue], ...] = (
                (
                    "daily",
                    {
                        "data": [
                            {
                                "calendarDate": DAY.isoformat(),
                                "heartRate": {"restingValue": 50},
                                "movement": {
                                    "steps": {
                                        "value": 4321,
                                        "goal": 9000,
                                        "distanceInMeters": 3210,
                                    },
                                },
                                "stress": {"avgLevel": 20},
                                "bodyBattery": {"minValue": 15, "maxValue": 90},
                            }
                        ]
                    },
                ),
                (
                    "sleep",
                    [
                        {
                            "calendarDate": DAY.isoformat(),
                            "sleepTimeSeconds": 28000,
                            "deepSleepSeconds": 4000,
                            "lightSleepSeconds": 17000,
                            "remSleepSeconds": 7000,
                            "awakeSleepSeconds": 800,
                        }
                    ],
                ),
                ("hrv", None),
            )
            for dataset, value in documents:
                store.write_json(
                    f"raw/wellness/{dataset}/{DAY}_{DAY}.json",
                    value,
                    dataset,
                    DAY.isoformat(),
                )
            zones: JsonValue = [
                {
                    "sport": "running",
                    "trainingMethod": "HR_MAX",
                    "zone1Floor": 100,
                    "zone2Floor": 120,
                    "zone3Floor": 140,
                    "zone4Floor": 160,
                    "zone5Floor": 180,
                    "maxHeartRateUsed": 200,
                }
            ]
            store.write_json("raw/profile/heart-rate-zones/current.json", zones, "zones", "current")
            session.add(ActivityAnnotation(activity_id=1, notes="Synthetic user-owned note"))
    finally:
        engine.dispose()
    return settings


def test_repeated_rebuild_exact_results_preserves_raw_operations_and_annotations() -> None:
    settings = _seed()
    engine = database_engine(settings.data_dir)
    try:
        with Session(engine) as session:
            manifest = {row.relative_path: row.sha256 for row in session.scalars(select(RawFile))}
        first, second = rebuild(settings), rebuild(settings)
        assert first.imported_activities == second.imported_activities == 2
        assert first.failed_activities == first.failed_documents == 0
        assert first.matches_previous is None and second.matches_previous is True
        with Session(engine) as session:
            activity = session.get(Activity, 1)
            assert activity is not None
            assert activity.is_race
            assert activity.distance_m == 18 and activity.avg_cadence_spm == 161
            assert activity.utc_offset_s == 3600 and activity.end_utc_offset_s == 7200
            assert activity.local_date == DAY
            assert activity.hr_source == "unknown"
            assert "hr_dropout" in activity.dq_flags
            assert session.scalar(select(func.count()).select_from(ActivityRecord)) == 12
            annotation = session.get(ActivityAnnotation, 1)
            assert annotation is not None and annotation.notes == "Synthetic user-owned note"
            assert session.get(SyncRun, "synthetic") is not None
            assert session.get(SyncCursor, "activities") is not None
            day = session.get(DailyWellness, DAY)
            sleep = session.get(SleepNight, DAY)
            hrv = session.get(HrvNight, DAY)
            assert day is not None and day.resting_hr_bpm == 50 and day.steps == 4321
            assert sleep is not None and sleep.duration_s == 28000 and sleep.score is None
            assert hrv is not None and hrv.last_night_avg_ms is None
            assert session.scalar(select(func.count()).select_from(ZoneSnapshot)) == 1
            assert manifest == {
                row.relative_path: row.sha256 for row in session.scalars(select(RawFile))
            }
        for path, digest in manifest.items():
            assert hashlib.sha256((settings.data_dir / path).read_bytes()).hexdigest() == digest
        assert quality_report(settings) > 0
        report = json.loads((settings.data_dir / "reports" / "data-quality.json").read_bytes())
        assert len(report["activities"]) == 2
    finally:
        engine.dispose()


def test_corrupt_fit_is_quarantined_reported_and_other_run_imports() -> None:
    settings = _seed(bad_second=True)
    result = runner.invoke(app, ["rebuild"])
    assert result.exit_code == 1, result.output
    assert "Activities imported: 1" in result.output
    assert "Activities reported as failed: 1" in result.output
    assert "Synthetic private" not in result.output
    assert str(settings.data_dir) not in result.output
    assert "synthetic-key" not in result.output
    quarantine = list((settings.data_dir / "quarantine").glob("*.zip"))
    assert len(quarantine) == 1
    original = settings.data_dir / "raw" / "activities" / "2030" / "2" / "original.zip"
    assert original.read_bytes() == quarantine[0].read_bytes()
    report = json.loads((settings.data_dir / "reports" / "data-quality.json").read_bytes())
    assert any(
        row.get("status") == "failed" and row.get("code") == "fit_integrity"
        for row in report["activities"]
    )
    assert rebuild(settings).matches_previous is True
    assert runner.invoke(app, ["dq-report"]).exit_code == 0


def test_rebuild_rollback_keeps_previous_measurements_on_storage_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _seed()
    rebuild(settings)

    def fail_documents(*_args: object) -> int:
        raise OSError("Synthetic disk failure")

    monkeypatch.setattr("stridelog.rebuild._documents", fail_documents)
    assert runner.invoke(app, ["rebuild"]).exit_code == 1
    engine = database_engine(settings.data_dir)
    try:
        with Session(engine) as session:
            assert session.scalar(select(func.count()).select_from(Activity)) == 2
            assert session.get(ActivityAnnotation, 1) is not None
    finally:
        engine.dispose()


def test_offline_cli_success_empty_guard_and_shared_lock() -> None:
    assert runner.invoke(app, ["rebuild"]).exit_code == 1
    assert runner.invoke(app, ["dq-report"]).exit_code == 1
    settings = _seed()
    assert runner.invoke(app, ["dq-report"]).exit_code == 1
    with sync_lock(settings.data_dir), pytest.raises(StridelogError, match="Another sync"):
        rebuild(settings)
    assert runner.invoke(app, ["rebuild"]).exit_code == 0
    result = runner.invoke(app, ["rebuild"])
    assert result.exit_code == 0 and "Matches previous rebuild: yes" in result.output


def test_changed_json_updates_without_duplicate_rows_and_missing_input_is_reported() -> None:
    settings = _seed()
    rebuild(settings)
    engine = database_engine(settings.data_dir)
    try:
        with Session(engine) as session, session.begin():
            store = RawStore(settings.data_dir, session, "synthetic")
            store.write_json(
                "raw/activities/2030/1/details.json",
                {"activityId": "1", "eventTypeDTO": {"typeKey": "training"}},
                "activities",
                "1",
            )
        report = rebuild(settings)
        assert report.matches_previous is False
        with Session(engine) as session:
            item = session.get(Activity, 1)
            assert item is not None and not item.is_race
            assert session.scalar(select(func.count()).select_from(Activity)) == 2
        (settings.data_dir / "raw" / "activities" / "2030" / "2" / "summary.json").unlink()
        assert rebuild(settings).failed_activities == 1
        with Session(engine) as session:
            assert (
                session.get(QualityIssue, ("activity_failure", "2", "archive_integrity"))
                is not None
            )
            assert session.get(ActivityAnnotation, 1) is not None
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    ("dataset", "payload", "code"),
    [
        ("daily", {"other": []}, "daily_container_missing"),
        ("daily", {"data": [{"calendarDate": "2030-04-01"}]}, "daily_date_mismatch"),
        ("sleep", [dict[str, object](), dict[str, object]()], "ambiguous_daily_rows"),
        ("sleep", {"data": []}, "daily_array_expected"),
        ("hrv", [{"unverified": 42}], "hrv_populated_schema_unverified"),
        ("daily", {"data": [{"movement": {"steps": {"value": True}}}]}, "json_number_invalid"),
        ("daily", {"data": [{"movement": {"steps": {"value": 10**400}}}]}, "json_number_invalid"),
        ("daily", {"data": [{"movement": {"steps": 1234}}]}, "json_object_expected"),
    ],
)
def test_unverified_or_ambiguous_wellness_never_silently_becomes_zero(
    dataset: str,
    payload: object,
    code: str,
) -> None:
    with pytest.raises(MappingError, match=code):
        wellness(dataset, payload, DAY)


@pytest.mark.parametrize(
    ("steps", "expected"),
    [
        (None, None),
        (dict[str, object](), None),
        ({"value": None}, None),
        ({"value": 0}, 0),
        ({"value": 4321, "goal": 9000, "distanceInMeters": 3210}, 4321),
    ],
)
def test_daily_steps_uses_nested_actual_value_not_goal_or_distance(
    steps: object,
    expected: float | None,
) -> None:
    mapped = wellness("daily", {"data": [{"movement": {"steps": steps}}]}, DAY)
    assert mapped["steps"] == expected


def test_bad_document_recorded_and_zone_history_preserved() -> None:
    settings = _seed()
    engine = database_engine(settings.data_dir)
    try:
        with Session(engine) as session, session.begin():
            store = RawStore(settings.data_dir, session, "synthetic")
            store.write_json(
                f"raw/wellness/hrv/{DAY}_{DAY}.json",
                [{"unverified": 42}],
                "hrv",
                DAY.isoformat(),
            )
            store.write_json(
                "raw/profile/heart-rate-zones/current.json",
                [{"sport": "running", "zone1Floor": 110}],
                "zones",
                "current",
            )
        assert rebuild(settings).failed_documents == 1
        with Session(engine) as session:
            assert session.scalar(select(func.count()).select_from(ZoneSnapshot)) == 2
            assert session.get(HrvNight, DAY) is None
        assert rebuild(settings).matches_previous is True
    finally:
        engine.dispose()


def test_start_offsets_never_use_end_offset_or_machine_timezone() -> None:
    parsed = decode_fit(running_fit(offset_s=7200))
    assert start_offset({}, parsed.start_time_utc) == (None, None)
    with pytest.raises(MappingError, match="fit_api_start_mismatch"):
        start_offset(
            {
                "startTimeGMT": "2030-03-30 00:59:58",
                "startTimeLocal": "2030-03-30 01:59:58",
            },
            parsed.start_time_utc,
        )
    with pytest.raises(MappingError, match="zones_sport_invalid"):
        zone_rows([{"sport": "running"}, {"sport": "running"}])


def test_quality_screens_artifacts_without_modifying_input() -> None:
    parsed = decode_fit(running_fit(samples=70))
    samples = tuple(
        replace(sample, heart_rate_bpm=161, cadence_spm=161) for sample in parsed.samples
    )
    activity = replace(parsed, samples=samples)
    flags = activity_flags(activity, 2000)
    assert {"hr_flatline", "possible_cadence_lock", "distance_total_mismatch"} <= set(flags)
    altered = list(samples)
    altered[2] = replace(altered[2], heart_rate_bpm=250, lat_deg=45, lon_deg=45)
    altered[3] = replace(altered[3], heart_rate_bpm=None)
    altered[-1] = replace(altered[-1], ts_utc=altered[-2].ts_utc - timedelta(seconds=1))
    flags = activity_flags(replace(parsed, samples=tuple(altered)), 210)
    assert {
        "hr_out_of_range",
        "hr_spike",
        "gps_jump",
        "hr_dropout",
        "non_increasing_record_time",
    } <= set(flags)
    assert activity.samples[2].heart_rate_bpm == 161
