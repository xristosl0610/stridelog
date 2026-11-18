"""Running metric checks use invented time series only."""

import math
from datetime import UTC, datetime, timedelta

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from stridelog.analytics import (
    DISTANCE_INTERPOLATION_GAP_S,
    AthleteInputs,
    BestEffort,
    EffortLap,
    PreparedPoint,
    SamplePoint,
    aerobic_decoupling_percent,
    calculate_best_efforts,
    calculate_lap_effort,
    calculate_splits,
    moving_time_s,
    pace_at_heart_rate_s_per_km,
    prepare_stream,
    race_predictions,
    time_in_zones_s,
    trimp,
)

START = datetime(2030, 1, 1, tzinfo=UTC)


def _sample(
    seconds: int,
    *,
    distance_m: float | None,
    speed_mps: float | None = 2.0,
    altitude_m: float | None = 20.0,
    heart_rate_bpm: float | None = 120.0,
) -> SamplePoint:
    return SamplePoint(
        START + timedelta(seconds=seconds),
        distance_m,
        altitude_m,
        speed_mps,
        heart_rate_bpm,
        160.0,
    )


def _point(seconds: int, distance_m: float, hr: float | None = 150.0) -> PreparedPoint:
    return PreparedPoint(
        START + timedelta(seconds=seconds),
        distance_m,
        20.0,
        2.5,
        hr,
        160.0,
        0.0,
        True,
        float(seconds),
    )


def test_prepare_stream_interpolates_short_gaps_and_preserves_long_gaps() -> None:
    short = prepare_stream(
        [_sample(0, distance_m=0), _sample(2, distance_m=4)],
        elevation_window_m=20,
    )
    assert len(short) == 3
    assert short[1].distance_m == 2
    assert short[1].heart_rate_bpm == 120

    long = prepare_stream(
        [_sample(0, distance_m=0), _sample(6, distance_m=12)],
        elevation_window_m=20,
    )
    assert [point.distance_m for point in long] == [0, None, None, None, None, None, 12]


def test_prepare_stream_does_not_extrapolate_or_invent_missing_sensor_values() -> None:
    points = prepare_stream(
        [
            _sample(0, distance_m=0, heart_rate_bpm=None),
            _sample(2, distance_m=4, heart_rate_bpm=120),
        ]
    )
    assert points[1].heart_rate_bpm is None


def test_zero_distance_change_has_no_grade() -> None:
    points = prepare_stream(
        [
            _sample(0, distance_m=0, altitude_m=10),
            _sample(1, distance_m=0, altitude_m=20),
            _sample(2, distance_m=2, altitude_m=30),
        ]
    )
    assert points[1].grade is None


def test_splits_interpolate_boundaries_and_keep_final_partial_split() -> None:
    points = [_point(seconds, seconds * 1.1) for seconds in range(1_201)]
    splits = calculate_splits(points)
    assert len(splits) == 2
    assert splits[0].distance_m == 1_000
    assert math.isclose(splits[0].duration_s, 1_000 / 1.1)
    assert math.isclose(splits[1].distance_m, 320)
    assert math.isclose(splits[1].duration_s, 320 / 1.1)


def test_best_efforts_do_not_bridge_long_record_gaps() -> None:
    points = [
        _point(0, 0),
        _point(2, 4),
        _point(20, 8),
        _point(22, 12),
    ]
    assert calculate_best_efforts(points, [200]) == ()


def test_distance_metrics_respect_gap_and_speed_boundaries() -> None:
    def efforts(interval: int, speed: float) -> tuple[BestEffort, ...]:
        samples = [_sample(second, distance_m=second * speed) for second in range(0, 301, interval)]
        points = prepare_stream(samples, max_gap_s=DISTANCE_INTERPOLATION_GAP_S)
        return calculate_best_efforts(points, [400])

    assert efforts(10, 4) == (BestEffort(400, 100),)
    assert efforts(11, 4) == ()
    assert efforts(10, 16) == ()


def test_lap_effort_interpolates_at_either_window_boundary() -> None:
    laps = [
        EffortLap(0, START, START + timedelta(seconds=100), 1_000, 100, 100),
        EffortLap(
            1, START + timedelta(seconds=100), START + timedelta(seconds=500), 1_000, 400, 400
        ),
    ]
    assert calculate_lap_effort(laps, 1_500) == BestEffort(1_500, 300)
    assert calculate_lap_effort(laps, 3_001) is None


def test_lap_effort_does_not_bridge_invalid_or_discontinuous_laps() -> None:
    laps = [
        EffortLap(0, START, START + timedelta(seconds=100), 1_000, 100, 100),
        EffortLap(
            1, START + timedelta(seconds=100), START + timedelta(seconds=200), None, 100, 100
        ),
        EffortLap(
            2, START + timedelta(seconds=200), START + timedelta(seconds=300), 1_000, 100, 100
        ),
        EffortLap(
            4, START + timedelta(seconds=300), START + timedelta(seconds=400), 1_000, 100, 100
        ),
    ]
    assert calculate_lap_effort(laps, 1_500) is None
    implausible = [EffortLap(0, START, START + timedelta(seconds=10), 1_000, 10, 10)]
    assert calculate_lap_effort(implausible, 400) is None


def test_lap_effort_allows_small_boundary_rounding_but_not_large_gaps() -> None:
    first = EffortLap(0, START, START + timedelta(seconds=100), 1_000, 100, 100)
    rounded = EffortLap(
        1, START + timedelta(seconds=101), START + timedelta(seconds=201), 1_000, 100, 100
    )
    distant = EffortLap(
        1, START + timedelta(seconds=102), START + timedelta(seconds=202), 1_000, 100, 100
    )
    assert calculate_lap_effort([first, rounded], 2_000) == BestEffort(2_000, 200)
    assert calculate_lap_effort([first, distant], 2_000) is None


@pytest.mark.parametrize("timer", [0.0, float("nan"), 102.0])
def test_lap_effort_rejects_invalid_timer_totals(timer: float) -> None:
    lap = EffortLap(0, START, START + timedelta(seconds=100), 1_000, timer, 100)
    assert calculate_lap_effort([lap], 400) is None


def test_lap_effort_uses_elapsed_total_when_timestamps_disagree() -> None:
    lap = EffortLap(0, START, START + timedelta(seconds=80), 1_000, 100, 100)
    assert calculate_lap_effort([lap], 400) == BestEffort(400, 40)
    missing_elapsed = EffortLap(0, START, START + timedelta(seconds=100), 1_000, 100, None)
    assert calculate_lap_effort([missing_elapsed], 400) is None


def test_splits_do_not_report_a_truncated_segment_as_a_final_split() -> None:
    points = [_point(second, second * 3) for second in range(401)] + [_point(420, 1_300)]
    splits = calculate_splits(points)
    assert len(splits) == 1
    assert splits[0].distance_m == 1_000


def test_splits_do_not_start_after_an_initial_single_point_segment() -> None:
    points = [_point(0, 0)] + [_point(second, (second - 20) * 3) for second in range(20, 421)]
    assert calculate_splits(points) == ()


def test_time_in_zones_requires_dated_floors_and_respects_explicit_hr_exclusion() -> None:
    points = [
        _point(0, 0, 99),
        _point(1, 2, 100),
        _point(2, 4, 121),
        _point(3, 6, 140),
    ]
    assert time_in_zones_s(points, [100, 120]) == (1, 1, 1)
    assert time_in_zones_s(points, None) is None
    assert time_in_zones_s(points, [100, 120], invalid_hr=True) is None


def test_trimp_requires_complete_profile_and_uses_selected_constants() -> None:
    points = [_point(0, 0), _point(1, 2)]
    inputs = AthleteInputs(200, 50, "other", None)
    expected = (1 / 60) * (2 / 3) * 0.64 * math.exp(1.92 * 2 / 3)
    assert math.isclose(trimp(points, inputs) or 0, expected)
    assert trimp(points, AthleteInputs(200, 50, None, None)) is None
    assert trimp(points, inputs, invalid_hr=True) is None


def test_training_efficiency_and_decoupling_respect_duration_and_hr_exclusion() -> None:
    points = [_point(seconds, seconds * 2) for seconds in range(3_601)]
    assert aerobic_decoupling_percent(points, 3_599, is_steady_run=True) is None
    assert aerobic_decoupling_percent(points, 3_600, is_steady_run=False) is None
    assert aerobic_decoupling_percent(points, 3_600, is_steady_run=True) == 0
    assert aerobic_decoupling_percent(points, 3_600, is_steady_run=True, invalid_hr=True) is None


def test_pace_at_heart_rate_uses_inclusive_band_and_median() -> None:
    points = [
        _point(0, 0, 140),
        PreparedPoint(START + timedelta(seconds=1), 2, 20, 4, 150, 160, 0, True, 1),
        PreparedPoint(START + timedelta(seconds=2), 4, 20, 3, 151, 160, 0, True, 2),
        PreparedPoint(START + timedelta(seconds=3), 6, 20, 3, 145, 160, 0, True, 3),
    ]
    assert pace_at_heart_rate_s_per_km(points) == 325
    assert pace_at_heart_rate_s_per_km(points, invalid_hr=True) is None


@settings(max_examples=20, deadline=None)
@given(
    intervals=st.integers(min_value=1, max_value=1_200),
    distance_per_second=st.floats(
        min_value=0.6,
        max_value=10.0,
        allow_nan=False,
        allow_infinity=False,
    ),
)
def test_split_distances_and_durations_reconcile_for_linear_streams(
    intervals: int,
    distance_per_second: float,
) -> None:
    points = [_point(second, second * distance_per_second) for second in range(intervals + 1)]
    splits = calculate_splits(points)
    assert math.isclose(sum(split.distance_m for split in splits), intervals * distance_per_second)
    assert math.isclose(
        sum(split.duration_s for split in splits),
        intervals,
        abs_tol=1e-6,
    )


def test_race_predictions_are_positive_and_use_available_efforts() -> None:
    predictions = race_predictions(
        5_000,
        1_500,
        [BestEffort(1_500, 300), BestEffort(2_500, 600)],
        [10_000],
    )
    assert len(predictions) == 1
    assert math.isclose(predictions[0].riegel_time_s, 1_500 * 2**1.06)
    assert predictions[0].vdot_time_s is not None
    assert predictions[0].critical_speed_time_s is not None


def test_moving_time_prefers_timer_and_uses_speed_only_as_fallback() -> None:
    points = [_point(0, 0), _point(1, 2), _point(2, 4)]
    assert moving_time_s(points, 1.5) == 1.5
    assert moving_time_s(points, None) == 2


def test_timer_events_exclude_paused_seconds_from_hr_metrics() -> None:
    samples = [_sample(seconds, distance_m=seconds * 3) for seconds in range(6)]
    points = prepare_stream(
        samples,
        timer_events=[
            (START, "start"),
            (START + timedelta(seconds=2), "stop_all"),
            (START + timedelta(seconds=3), "start"),
        ],
    )
    assert [point.timer_active for point in points] == [True, True, False, True, True, True]
    assert [point.active_time_s for point in points] == [0, 1, 2, 2, 3, 4]
    assert sum(time_in_zones_s(points, [100]) or ()) == 4
    expected_one_second = (1 / 60) * (70 / 150) * 0.64 * math.exp(1.92 * 70 / 150)
    assert math.isclose(
        trimp(points, AthleteInputs(200, 50, "other", None)) or 0,
        4 * expected_one_second,
    )
