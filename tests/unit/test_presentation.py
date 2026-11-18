"""Display conversions use invented values and do not alter stored SI units."""

import pytest

from stridelog.presentation import (
    distance_label,
    format_duration,
    pace_seconds_per_km,
    pace_ticks,
)


def test_pace_conversion_and_duration_formatting() -> None:
    assert pace_seconds_per_km(4.0) == 250
    assert format_duration(250) == "4:10"
    assert format_duration(3599.8) == "1:00:00"
    assert pace_seconds_per_km(0) is None
    assert pace_seconds_per_km(None) is None
    with pytest.raises(ValueError):
        pace_seconds_per_km(float("nan"))


def test_standard_effort_distances_have_readable_labels() -> None:
    assert distance_label(400) == "400 m"
    assert distance_label(1_000) == "1 km"
    assert distance_label(1_609.344) == "1 mile"
    assert distance_label(21_097.5) == "Half marathon"
    with pytest.raises(ValueError):
        distance_label(0)


def test_pace_axis_ticks_use_clock_labels_and_ignore_missing_pace() -> None:
    values, labels = pace_ticks([250, None, 300])
    assert values == [240, 270, 300]
    assert labels == ["4:00", "4:30", "5:00"]
    assert pace_ticks([None]) == ([], [])
