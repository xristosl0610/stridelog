"""Analysis persistence tests use only synthetic SQLite rows."""

from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import cast

import pytest
from sqlalchemy import delete
from sqlalchemy.orm import Session
from typer.testing import CliRunner

from stridelog.analysis import analyze, personal_record_progression
from stridelog.cli import app
from stridelog.config import Settings
from stridelog.db.engine import database_engine, initialize_database
from stridelog.db.models import (
    Activity,
    ActivityAnalytics,
    ActivityAnnotation,
    ActivityLap,
    ActivityRecord,
    AthleteProfile,
    DailyAnalytics,
    DailyWellness,
)

pytestmark = pytest.mark.usefixtures("private_environment")
DAY = date(2030, 3, 31)
START = datetime(2030, 3, 31, 0, 0, tzinfo=UTC)
runner = CliRunner()


def _seed(data_dir: Path) -> None:
    initialize_database(data_dir)
    engine = database_engine(data_dir)
    try:
        with Session(engine) as session, session.begin():
            session.add(
                Activity(
                    id=1,
                    name="Synthetic",
                    activity_type="running",
                    event_type=None,
                    is_race=False,
                    start_time_utc=START.isoformat(),
                    utc_offset_s=0,
                    end_utc_offset_s=0,
                    local_date=DAY,
                    distance_m=15.0,
                    timer_time_s=5.0,
                    elapsed_time_s=5.0,
                    avg_hr_bpm=150.0,
                    avg_cadence_spm=160.0,
                    hr_source="unknown",
                    hr_source_origin="unknown",
                    dq_flags=["hr_dropout"],
                    source_checksums={"synthetic.fit": "a" * 64},
                    garmin_metrics={},
                    parser_version=1,
                )
            )
            session.add_all(
                ActivityRecord(
                    activity_id=1,
                    record_index=index,
                    ts_utc=(START + timedelta(seconds=index)).isoformat(),
                    distance_m=index * 3.0,
                    lat_deg=None,
                    lon_deg=None,
                    altitude_m=20.0 + index,
                    speed_mps=3.0,
                    heart_rate_bpm=150.0,
                    cadence_spm=160.0,
                )
                for index in range(6)
            )
            session.add(
                DailyWellness(
                    local_date=DAY + timedelta(days=2),
                    resting_hr_bpm=50.0,
                    steps=1_234,
                    stress_avg=20.0,
                    body_battery_high=80.0,
                    body_battery_low=10.0,
                    raw_path="synthetic.json",
                    raw_sha256="b" * 64,
                )
            )
    finally:
        engine.dispose()


def test_analysis_caches_per_activity_and_uses_only_dated_profiles() -> None:
    settings = Settings()
    _seed(settings.data_dir)
    engine = database_engine(settings.data_dir)
    try:
        first = analyze(settings)
        assert first.calculated_activities == 1
        assert first.skipped_activities == 0
        assert first.calculated_days == 3
        with Session(engine) as session:
            metrics = session.get(ActivityAnalytics, 1)
            day_metrics = session.get(DailyAnalytics, DAY)
            wellness_metrics = session.get(DailyAnalytics, DAY + timedelta(days=2))
            assert metrics is not None
            assert metrics.metrics["time_in_zones_s"] is None
            assert metrics.metrics["training_load_trimp"] is None
            assert day_metrics is not None
            assert day_metrics.metrics["training_load_trimp"] is None
            assert wellness_metrics is not None
            assert wellness_metrics.metrics["steps"] == 1_234
            assert wellness_metrics.metrics["body_battery_low"] == 10

        assert analyze(settings).skipped_activities == 1
        with Session(engine) as session, session.begin():
            session.add(
                AthleteProfile(
                    effective_from=DAY,
                    max_hr_bpm=200,
                    resting_hr_bpm=50,
                    threshold_hr_bpm=170,
                    sex_for_trimp="other",
                    hr_zone_floors_bpm=[100, 120],
                )
            )
        updated = analyze(settings)
        assert updated.calculated_activities == 1
        assert updated.skipped_activities == 0
        with Session(engine) as session:
            metrics = session.get(ActivityAnalytics, 1)
            assert metrics is not None
            assert metrics.metrics["time_in_zones_s"] == [0, 0, 5]
            load = metrics.metrics["training_load_trimp"]
            assert isinstance(load, float) and load > 0
    finally:
        engine.dispose()


def test_distance_metrics_use_longer_gaps_without_interpolating_heart_rate() -> None:
    settings = Settings()
    _seed(settings.data_dir)
    engine = database_engine(settings.data_dir)
    try:
        with Session(engine) as session, session.begin():
            session.execute(delete(ActivityRecord))
            session.add_all(
                ActivityRecord(
                    activity_id=1,
                    record_index=index,
                    ts_utc=(START + timedelta(seconds=second)).isoformat(),
                    distance_m=second * 3.0,
                    lat_deg=None,
                    lon_deg=None,
                    altitude_m=None,
                    speed_mps=3.0,
                    heart_rate_bpm=150.0,
                    cadence_spm=160.0,
                )
                for index, second in enumerate(range(0, 421, 7))
            )
            session.add(
                AthleteProfile(
                    effective_from=DAY,
                    max_hr_bpm=200,
                    resting_hr_bpm=50,
                    threshold_hr_bpm=None,
                    sex_for_trimp="other",
                    hr_zone_floors_bpm=[100, 120],
                )
            )

        assert analyze(settings).calculated_activities == 1
        with Session(engine) as session:
            cached = session.get(ActivityAnalytics, 1)
            assert cached is not None
            assert cached.metrics["time_in_zones_s"] == [0, 0, 60]
            assert cached.metrics["splits"] == [
                {"index": 1, "distance_m": 1_000, "duration_s": pytest.approx(1_000 / 3)},
                {"index": 2, "distance_m": 260, "duration_s": pytest.approx(260 / 3)},
            ]
            assert cached.metrics["best_efforts"] == [
                {"distance_m": 400, "duration_s": pytest.approx(400 / 3)},
                {"distance_m": 1_000, "duration_s": pytest.approx(1_000 / 3)},
            ]
        with Session(engine) as session, session.begin():
            cached = session.get(ActivityAnalytics, 1)
            assert cached is not None
            cached.algorithm_version -= 1
        assert analyze(settings).calculated_activities == 1
    finally:
        engine.dispose()


def test_lap_marathon_fallback_is_separate_from_sampled_records() -> None:
    settings = Settings()
    _seed(settings.data_dir)
    engine = database_engine(settings.data_dir)
    try:
        with Session(engine) as session, session.begin():
            session.add_all(
                ActivityLap(
                    activity_id=1,
                    lap_index=index,
                    start_time_utc=(START + timedelta(seconds=index * 300)).isoformat(),
                    end_time_utc=(START + timedelta(seconds=(index + 1) * 300)).isoformat(),
                    distance_m=1_000,
                    timer_time_s=302,
                    elapsed_time_s=302,
                    avg_hr_bpm=None,
                    avg_cadence_spm=None,
                    intensity=None,
                    trigger=None,
                )
                for index in range(43)
            )
        assert analyze(settings).calculated_activities == 1
        with Session(engine) as session:
            cached = session.get(ActivityAnalytics, 1)
            assert cached is not None
            assert cached.metrics["best_efforts"] == []
            assert cached.metrics["lap_estimated_marathon"] == {
                "distance_m": 42_195,
                "duration_s": pytest.approx(42_195 * 0.302),
            }
        with Session(engine) as session, session.begin():
            session.execute(delete(ActivityRecord))
            session.add_all(
                ActivityRecord(
                    activity_id=1,
                    record_index=index,
                    ts_utc=(START + timedelta(seconds=second)).isoformat(),
                    distance_m=second * 14.0,
                    lat_deg=None,
                    lon_deg=None,
                    altitude_m=None,
                    speed_mps=14.0,
                    heart_rate_bpm=None,
                    cadence_spm=None,
                )
                for index, second in enumerate(range(0, 3_101, 10))
            )
            cached = session.get(ActivityAnalytics, 1)
            assert cached is not None
            cached.algorithm_version -= 1
        assert analyze(settings).calculated_activities == 1
        with Session(engine) as session:
            cached = session.get(ActivityAnalytics, 1)
            assert cached is not None
            assert cached.metrics["lap_estimated_marathon"] is None
            efforts = cached.metrics["best_efforts"]
            assert isinstance(efforts, list)
            assert {"distance_m": 42_195, "duration_s": pytest.approx(42_195 / 14)} in cast(
                "list[object]", efforts
            )
    finally:
        engine.dispose()


def test_profile_command_saves_without_echoing_private_values() -> None:
    result = runner.invoke(
        app,
        [
            "profile",
            "set",
            DAY.isoformat(),
            "--max-hr-bpm",
            "200",
            "--resting-hr-bpm",
            "50",
            "--sex-for-trimp",
            "other",
            "--zone-floors",
            "100,120,140,160,180",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "Athlete profile saved" in result.output
    assert "200" not in result.output and "50" not in result.output


def test_profile_command_rejects_non_increasing_zone_floors() -> None:
    result = runner.invoke(
        app,
        [
            "profile",
            "set",
            DAY.isoformat(),
            "--max-hr-bpm",
            "200",
            "--resting-hr-bpm",
            "50",
            "--sex-for-trimp",
            "other",
            "--zone-floors",
            "100,120,110,160,180",
        ],
    )
    assert result.exit_code == 1
    assert "five increasing values" in result.output


def test_interactive_profile_saves_hidden_inputs_and_refreshes_analysis() -> None:
    settings = Settings()
    _seed(settings.data_dir)
    result = runner.invoke(
        app,
        ["profile", "setup"],
        input="2030-03-31\n200\n50\nother\n\n100,120,140,160,180\n",
    )
    assert result.exit_code == 0, result.output
    assert "Athlete profile saved" in result.output
    for value in ("2030-03-31", "200", "50", "100,120,140,160,180"):
        assert value not in result.output
    engine = database_engine(settings.data_dir)
    try:
        with Session(engine) as session:
            profile = session.get(AthleteProfile, DAY)
            metrics = session.get(ActivityAnalytics, 1)
            assert profile is not None
            assert profile.max_hr_bpm == 200 and profile.resting_hr_bpm == 50
            assert profile.hr_zone_floors_bpm == [100, 120, 140, 160, 180]
            assert metrics is not None and metrics.metrics["training_load_trimp"] is not None
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    ("inputs", "message"),
    [
        ("2030-03-31\nnot-a-number\n50\nother\n\n\n", "Heart-rate values must be numbers."),
        ("2030-03-31\n200\n50\ninvalid\n\n\n", "TRIMP constants must be female or other."),
        ("2030-03-31\n200\n50\nother\n\n100,90,140,160,180\n", "five increasing values"),
    ],
)
def test_interactive_profile_rejects_invalid_values_without_echo(inputs: str, message: str) -> None:
    result = runner.invoke(app, ["profile", "setup"], input=inputs)
    assert result.exit_code == 1
    assert message in result.output
    assert "not-a-number" not in result.output
    assert "2030-03-31" not in result.output
    assert "100,90,140,160,180" not in result.output
    assert not (Settings().data_dir / "stridelog.sqlite").exists()


def test_steady_run_command_saves_annotation_and_refreshes_metrics() -> None:
    settings = Settings()
    _seed(settings.data_dir)
    result = runner.invoke(app, ["activity", "steady-run", "1", "--steady"])
    assert result.exit_code == 0, result.output
    assert "Steady-run annotation saved" in result.output
    assert "Synthetic" not in result.output
    engine = database_engine(settings.data_dir)
    try:
        with Session(engine) as session:
            annotation = session.get(ActivityAnnotation, 1)
            metrics = session.get(ActivityAnalytics, 1)
            assert annotation is not None and annotation.is_steady_run
            assert metrics is not None
            assert metrics.metrics["aerobic_decoupling_percent"] is None
        result = runner.invoke(app, ["activity", "steady-run", "1", "--not-steady"])
        assert result.exit_code == 0, result.output
        with Session(engine) as session:
            annotation = session.get(ActivityAnnotation, 1)
            assert annotation is not None and not annotation.is_steady_run
    finally:
        engine.dispose()


def test_race_command_saves_override_and_official_time_privately() -> None:
    settings = Settings()
    _seed(settings.data_dir)
    result = runner.invoke(
        app,
        [
            "activity",
            "race",
            "1",
            "--race",
            "--race-name",
            "Synthetic race",
            "--official-time-s",
            "1500",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "Synthetic race" not in result.output and "1500" not in result.output
    engine = database_engine(settings.data_dir)
    try:
        with Session(engine) as session:
            annotation = session.get(ActivityAnnotation, 1)
            metrics = session.get(ActivityAnalytics, 1)
            assert annotation is not None
            assert annotation.is_race_override is True
            assert annotation.race_name == "Synthetic race"
            assert annotation.official_time_s == 1_500
            assert metrics is not None
            assert metrics.metrics["race_predictions"]
        result = runner.invoke(app, ["activity", "race", "1", "--not-race"])
        assert result.exit_code == 0, result.output
        with Session(engine) as session:
            annotation = session.get(ActivityAnnotation, 1)
            assert annotation is not None
            assert annotation.is_race_override is False
            assert annotation.race_name is None
            assert annotation.official_time_s is None
        result = runner.invoke(app, ["activity", "race", "1", "--from-garmin"])
        assert result.exit_code == 0, result.output
        with Session(engine) as session:
            annotation = session.get(ActivityAnnotation, 1)
            assert annotation is not None
            assert annotation.is_race_override is None
    finally:
        engine.dispose()


def test_personal_record_progression_tracks_only_new_fastest_efforts() -> None:
    first = Activity(id=1, local_date=DAY)
    second = Activity(id=2, local_date=DAY + timedelta(days=1))
    third = Activity(id=3, local_date=DAY + timedelta(days=2))
    excluded = Activity(id=4, local_date=DAY + timedelta(days=3))
    progression = personal_record_progression(
        [first, second, third, excluded],
        {4: ActivityAnnotation(activity_id=4, exclude_from_stats=True, hr_invalid=False)},
        {
            1: {"best_efforts": [{"distance_m": 1_000.0, "duration_s": 300.0}]},
            2: {"best_efforts": [{"distance_m": 1_000.0, "duration_s": 290.0}]},
            3: {"best_efforts": [{"distance_m": 1_000.0, "duration_s": 295.0}]},
            4: {"best_efforts": [{"distance_m": 1_000.0, "duration_s": 280.0}]},
        },
    )
    assert progression[DAY] == [{"distance_m": 1_000.0, "time_s": 300.0}]
    assert progression[DAY + timedelta(days=1)] == [{"distance_m": 1_000.0, "time_s": 290.0}]
    assert DAY + timedelta(days=2) not in progression
    assert DAY + timedelta(days=3) not in progression
