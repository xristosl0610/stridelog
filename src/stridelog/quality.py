"""Conservative screening flags, not medical judgments or automatic data removal."""

import math
from itertools import pairwise

from stridelog.fit import ParsedActivity


def activity_flags(
    parsed: ParsedActivity,
    summary_distance: float | None,
    *,
    summary_timer: float | None = None,
    summary_elapsed: float | None = None,
) -> list[str]:
    """Flag plausible artifacts using documented fixed thresholds; retain original samples."""
    flags: set[str] = set()
    samples = parsed.samples
    if any(sample.heart_rate_bpm is None or sample.heart_rate_bpm == 0 for sample in samples):
        flags.add("hr_dropout")
    if any(
        sample.heart_rate_bpm is not None and not 30 <= sample.heart_rate_bpm <= 240
        for sample in samples
    ):
        flags.add("hr_out_of_range")
    equal_hr = 0
    locked_since: float | None = None
    flat_since: float | None = None
    for left, right in pairwise(samples):
        dt = (right.ts_utc - left.ts_utc).total_seconds()
        if dt <= 0:
            flags.add("non_increasing_record_time")
            continue
        if dt > 30:
            flags.add("record_gap")
        if left.heart_rate_bpm is not None and right.heart_rate_bpm is not None:
            if dt <= 5 and abs(right.heart_rate_bpm - left.heart_rate_bpm) / dt > 15:
                flags.add("hr_spike")
            if left.heart_rate_bpm == right.heart_rate_bpm and dt <= 5:
                flat_since = left.ts_utc.timestamp() if flat_since is None else flat_since
                if right.ts_utc.timestamp() - flat_since >= 60:
                    flags.add("hr_flatline")
            else:
                flat_since = None
        else:
            flat_since = None
        if (
            right.heart_rate_bpm is not None
            and right.cadence_spm is not None
            and abs(right.heart_rate_bpm - right.cadence_spm) <= 3
            and dt <= 5
        ):
            locked_since = left.ts_utc.timestamp() if locked_since is None else locked_since
            equal_hr += 1
            if right.ts_utc.timestamp() - locked_since >= 60 and equal_hr >= 12:
                flags.add("possible_cadence_lock")
        else:
            locked_since = None
            equal_hr = 0
        if (
            None not in (left.lat_deg, left.lon_deg, right.lat_deg, right.lon_deg)
            and _gps_distance(left.lat_deg, left.lon_deg, right.lat_deg, right.lon_deg) / dt > 15
        ):
            flags.add("gps_jump")
    for name, actual, expected, tolerance in (
        ("distance_total_mismatch", parsed.distance_m, summary_distance, 10.0),
        ("timer_total_mismatch", parsed.timer_time_s, summary_timer, 2.0),
        ("elapsed_total_mismatch", parsed.elapsed_time_s, summary_elapsed, 2.0),
        (
            "lap_distance_mismatch",
            sum(lap.distance_m or 0 for lap in parsed.laps)
            if parsed.laps and all(lap.distance_m is not None for lap in parsed.laps)
            else None,
            parsed.distance_m,
            10.0,
        ),
    ):
        if (
            actual is not None
            and expected is not None
            and abs(actual - expected) > max(tolerance, 0.02 * abs(expected))
        ):
            flags.add(name)
    if not parsed.sensors:
        flags.add("missing_sensor_metadata")
    return sorted(flags)


def _gps_distance(
    lat1: float | None,
    lon1: float | None,
    lat2: float | None,
    lon2: float | None,
) -> float:
    if lat1 is None or lon1 is None or lat2 is None or lon2 is None:
        raise ValueError("GPS distance requires complete coordinates")
    radians = [math.radians(value) for value in (lat1, lon1, lat2, lon2)]
    a, b, c, d = radians
    h = math.sin((c - a) / 2) ** 2 + math.cos(a) * math.cos(c) * math.sin((d - b) / 2) ** 2
    return 6371000 * 2 * math.asin(math.sqrt(max(0.0, min(1.0, h))))
