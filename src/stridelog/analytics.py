"""Synthetic-testable running metrics; quality warnings never diagnose a source."""

import math
from bisect import bisect_left
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from itertools import pairwise
from statistics import fmean, median

import polars as pl

ANALYTICS_VERSION = 5
MAX_INTERPOLATION_GAP_S = 5
DISTANCE_INTERPOLATION_GAP_S = 10
MAX_PLAUSIBLE_SPEED_MPS = 15.0
SPLIT_DISTANCE_M = 1_000.0
BEST_EFFORT_DISTANCES_M = (
    400.0,
    1_000.0,
    1_609.344,
    5_000.0,
    10_000.0,
    15_000.0,
    16_093.44,
    21_097.5,
    30_000.0,
    42_195.0,
)


@dataclass(frozen=True)
class SamplePoint:
    """One decoded FIT record; missing sensor values remain missing."""

    timestamp: datetime
    distance_m: float | None
    altitude_m: float | None
    speed_mps: float | None
    heart_rate_bpm: float | None
    cadence_spm: float | None


@dataclass(frozen=True)
class PreparedPoint:
    """One point on the one-second analytics timeline."""

    timestamp: datetime
    distance_m: float | None
    altitude_m: float | None
    speed_mps: float | None
    heart_rate_bpm: float | None
    cadence_spm: float | None
    grade: float | None
    timer_active: bool = True
    active_time_s: float = 0.0


@dataclass(frozen=True)
class Split:
    """A full or final partial distance split."""

    index: int
    distance_m: float
    duration_s: float


@dataclass(frozen=True)
class BestEffort:
    """Fastest uninterrupted elapsed time over a requested distance."""

    distance_m: float
    duration_s: float


@dataclass(frozen=True)
class EffortLap:
    """Lap totals and boundaries used for a labelled distance-effort estimate."""

    index: int
    start: datetime
    end: datetime
    distance_m: float | None
    timer_time_s: float | None
    elapsed_time_s: float | None


@dataclass(frozen=True)
class AthleteInputs:
    """Dated, explicitly supplied inputs; absent values are never inferred."""

    max_hr_bpm: float | None
    resting_hr_bpm: float | None
    sex_for_trimp: str | None
    hr_zone_floors_bpm: tuple[float, ...] | None


@dataclass(frozen=True)
class RacePrediction:
    """Formula-based prediction from an actual race result."""

    distance_m: float
    riegel_time_s: float
    vdot_time_s: float | None
    critical_speed_time_s: float | None


def _interpolate(left: float | None, right: float | None, fraction: float) -> float | None:
    if left is None or right is None:
        return None
    return left + (right - left) * fraction


def _smoothed_altitudes(
    distances: Sequence[float | None],
    altitudes: Sequence[float | None],
    window_m: float,
) -> list[float | None]:
    result: list[float | None] = [None] * len(distances)
    start = 0
    half_window = window_m / 2
    while start < len(distances):
        while start < len(distances) and distances[start] is None:
            start += 1
        end = start
        decreased = False
        while end < len(distances) and distances[end] is not None:
            current_distance = distances[end]
            previous_distance = distances[end - 1] if end > start else None
            if (
                current_distance is not None
                and previous_distance is not None
                and current_distance < previous_distance
            ):
                decreased = True
                break
            end += 1
        if end == start:
            continue
        values = [float(value) for value in distances[start:end] if value is not None]
        prefix_sum = [0.0]
        prefix_count = [0]
        for altitude in altitudes[start:end]:
            prefix_sum.append(prefix_sum[-1] + (altitude or 0.0))
            prefix_count.append(prefix_count[-1] + (altitude is not None))
        for offset, distance in enumerate(values):
            left = bisect_left(values, distance - half_window)
            right = bisect_left(values, distance + half_window, lo=left)
            count = prefix_count[right] - prefix_count[left]
            result[start + offset] = (
                None if count == 0 else (prefix_sum[right] - prefix_sum[left]) / count
            )
        start = end if decreased else end + 1
    return result


def prepare_stream(
    samples: Sequence[SamplePoint],
    *,
    timer_events: Sequence[tuple[datetime, str]] = (),
    max_gap_s: float = MAX_INTERPOLATION_GAP_S,
    elevation_window_m: float = 20.0,
) -> tuple[PreparedPoint, ...]:
    """Resample without extrapolation; gaps over the approved limit stay null."""
    if not samples:
        return ()
    if max_gap_s <= 0 or elevation_window_m <= 0:
        raise ValueError("Resampling and smoothing windows must be positive.")
    ordered = sorted(samples, key=lambda sample: sample.timestamp)
    if any(sample.timestamp.utcoffset() is None for sample in ordered):
        raise ValueError("Sample timestamps must be timezone-aware.")
    unique: list[SamplePoint] = []
    for sample in ordered:
        if unique and sample.timestamp == unique[-1].timestamp:
            unique[-1] = sample
        else:
            unique.append(sample)

    start = unique[0].timestamp
    duration_s = (unique[-1].timestamp - start).total_seconds()
    ticks = [start + timedelta(seconds=index) for index in range(math.floor(duration_s) + 1)]
    ordered_events = sorted(timer_events)
    if any(timestamp.utcoffset() is None for timestamp, _ in ordered_events):
        raise ValueError("Timer event timestamps must be timezone-aware.")
    start_events = {"start", "resume"}
    stop_events = {"stop", "stop_all", "stop_disable"}
    controlled = any(event in start_events | stop_events for _, event in ordered_events)
    active = not any(event in start_events for _, event in ordered_events)
    event_index = 0
    timer_active: list[bool] = []
    for timestamp in ticks:
        while event_index < len(ordered_events) and ordered_events[event_index][0] <= timestamp:
            event = ordered_events[event_index][1]
            if event in start_events:
                active = True
            elif event in stop_events:
                active = False
            event_index += 1
        timer_active.append(active if controlled else True)
    active_time = [0.0] * len(ticks)
    for index in range(1, len(ticks)):
        active_time[index] = active_time[index - 1] + int(timer_active[index - 1])
    columns = (
        "distance_m",
        "altitude_m",
        "speed_mps",
        "heart_rate_bpm",
        "cadence_spm",
    )
    values: dict[str, list[float | None]] = {column: [] for column in columns}
    right_index = 0
    for timestamp in ticks:
        while right_index < len(unique) and unique[right_index].timestamp < timestamp:
            right_index += 1
        if right_index < len(unique) and unique[right_index].timestamp == timestamp:
            source = unique[right_index]
            for column in columns:
                values[column].append(getattr(source, column))
            continue
        left_index = right_index - 1
        if left_index < 0 or right_index >= len(unique):
            for column in columns:
                values[column].append(None)
            continue
        left, right = unique[left_index], unique[right_index]
        gap_s = (right.timestamp - left.timestamp).total_seconds()
        if gap_s > max_gap_s:
            for column in columns:
                values[column].append(None)
            continue
        fraction = (timestamp - left.timestamp).total_seconds() / gap_s
        for column in columns:
            values[column].append(
                _interpolate(getattr(left, column), getattr(right, column), fraction)
            )

    smoothed = _smoothed_altitudes(values["distance_m"], values["altitude_m"], elevation_window_m)
    # Polars keeps the derivative calculation vectorized for long recorded activities.
    frame = pl.DataFrame(
        {
            "distance_m": values["distance_m"],
            "altitude_m": smoothed,
        },
        schema={"distance_m": pl.Float64, "altitude_m": pl.Float64},
    )
    altitude_delta = pl.col("altitude_m").diff()  # pyright: ignore[reportUnknownMemberType]
    distance_delta = pl.col("distance_m").diff()  # pyright: ignore[reportUnknownMemberType]
    grade = (
        pl.when(distance_delta > 0)  # pyright: ignore[reportUnknownMemberType]
        .then((altitude_delta / distance_delta).clip(-0.45, 0.45))
        .otherwise(None)
        .alias("grade")
    )
    frame = frame.with_columns(  # pyright: ignore[reportUnknownMemberType]
        grade
    )
    grades = frame.get_column("grade").to_list()
    return tuple(
        PreparedPoint(
            timestamp,
            values["distance_m"][index],
            values["altitude_m"][index],
            values["speed_mps"][index],
            values["heart_rate_bpm"][index],
            values["cadence_spm"][index],
            grades[index],
            timer_active[index],
            active_time[index],
        )
        for index, timestamp in enumerate(ticks)
    )


def moving_time_s(points: Sequence[PreparedPoint], timer_time_s: float | None) -> float | None:
    """Prefer FIT timer time, otherwise count sampled seconds above 0.5 m/s."""
    if timer_time_s is not None:
        return timer_time_s
    return float(
        sum(point.timer_active and (point.speed_mps or 0.0) > 0.5 for point in points[:-1])
    )


def _distance_segments(
    points: Sequence[PreparedPoint],
) -> list[list[tuple[float, float]]]:
    segments: list[list[tuple[float, float]]] = []
    current: list[tuple[float, float]] = []
    previous: PreparedPoint | None = None
    for point in points:
        if point.distance_m is None:
            if current:
                segments.append(current)
            current, previous = [], None
            continue
        if previous is not None:
            seconds = (point.timestamp - previous.timestamp).total_seconds()
            delta = point.distance_m - (previous.distance_m or 0.0)
            if (
                seconds <= 0
                or seconds > MAX_INTERPOLATION_GAP_S
                or delta < 0
                or delta / seconds > MAX_PLAUSIBLE_SPEED_MPS
            ):
                if current:
                    segments.append(current)
                current = []
        current.append((point.distance_m, point.active_time_s))
        previous = point
    if current:
        segments.append(current)
    return segments


def _time_at_distance(
    segment: Sequence[tuple[float, float]],
    distance: float,
    distances: Sequence[float] | None = None,
) -> float | None:
    if distances is None:
        distances = [item[0] for item in segment]
    index = bisect_left(distances, distance)
    if index < len(segment) and distances[index] == distance:
        return segment[index][1]
    if index == 0 or index == len(segment):
        return None
    left_distance, left_time = segment[index - 1]
    right_distance, right_time = segment[index]
    if right_distance <= left_distance:
        return None
    fraction = (distance - left_distance) / (right_distance - left_distance)
    return left_time + (right_time - left_time) * fraction


def calculate_splits(points: Sequence[PreparedPoint]) -> tuple[Split, ...]:
    """Interpolate kilometer boundaries; only a complete stream has a final partial."""
    result: list[Split] = []
    first_index = next(
        (index for index, point in enumerate(points) if point.distance_m is not None), None
    )
    if first_index is None:
        return ()
    for segment in _distance_segments(points):
        if len(segment) < 2:
            break
        start, end = segment[0][0], segment[-1][0]
        start_time = _time_at_distance(segment, start)
        if start_time is None:
            continue
        split_index = 1
        boundary = start + SPLIT_DISTANCE_M
        while boundary <= end:
            boundary_time = _time_at_distance(segment, boundary)
            if boundary_time is None:
                break
            result.append(Split(split_index, SPLIT_DISTANCE_M, boundary_time - start_time))
            split_index += 1
            start_time = boundary_time
            boundary += SPLIT_DISTANCE_M
        partial = end - (boundary - SPLIT_DISTANCE_M)
        if partial > 0 and len(segment) == len(points) - first_index:
            end_time = _time_at_distance(segment, end)
            if end_time is not None:
                result.append(Split(split_index, partial, end_time - start_time))
        break
    return tuple(result)


def calculate_best_efforts(
    points: Sequence[PreparedPoint],
    distances_m: Sequence[float] = BEST_EFFORT_DISTANCES_M,
) -> tuple[BestEffort, ...]:
    """Find fastest distance windows without bridging missing or implausible spans."""
    result: list[BestEffort] = []
    segments = _distance_segments(points)
    for target in distances_m:
        best: float | None = None
        for segment in segments:
            distances = [item[0] for item in segment]
            first, last = distances[0], distances[-1]
            if last - first < target:
                continue
            for end_distance, end_time in segment:
                if end_distance - first < target:
                    continue
                start_time = _time_at_distance(segment, end_distance - target, distances)
                if start_time is None:
                    continue
                elapsed = end_time - start_time
                if elapsed > 0 and (best is None or elapsed < best):
                    best = elapsed
        if best is not None:
            result.append(BestEffort(target, best))
    return tuple(result)


def calculate_lap_effort(laps: Sequence[EffortLap], target_m: float) -> BestEffort | None:
    """Estimate a fastest window assuming constant speed within each valid lap."""
    if not math.isfinite(target_m) or target_m <= 0:
        raise ValueError("Target distance must be a positive finite number.")
    segments: list[list[tuple[float, float]]] = []
    current: list[tuple[float, float]] = []
    previous: EffortLap | None = None
    for lap in laps:
        duration = (lap.end - lap.start).total_seconds()
        distance, timer, elapsed = lap.distance_m, lap.timer_time_s, lap.elapsed_time_s
        valid = (
            distance is not None
            and timer is not None
            and elapsed is not None
            and math.isfinite(distance)
            and math.isfinite(timer)
            and math.isfinite(elapsed)
            and distance > 0
            and timer > 0
            and elapsed > 0
            and duration > 0
            and timer <= elapsed + 1
            and distance / timer <= MAX_PLAUSIBLE_SPEED_MPS
        )
        consecutive = previous is not None and (
            lap.index == previous.index + 1 and abs((lap.start - previous.end).total_seconds()) <= 1
        )
        if current and (not valid or not consecutive):
            segments.append(current)
            current = []
        if not valid or distance is None or timer is None:
            previous = None
            continue
        if not current:
            current = [(0.0, 0.0)]
        current.append((current[-1][0] + distance, current[-1][1] + timer))
        previous = lap
    if current:
        segments.append(current)

    best: float | None = None
    for segment in segments:
        distances = [distance for distance, _ in segment]
        for distance, time in segment:
            for other_distance, end_is_boundary in (
                (distance - target_m, True),
                (distance + target_m, False),
            ):
                other_time = _time_at_distance(segment, other_distance, distances)
                if other_time is None:
                    continue
                elapsed = time - other_time if end_is_boundary else other_time - time
                if elapsed > 0 and (best is None or elapsed < best):
                    best = elapsed
    return None if best is None else BestEffort(target_m, best)


def time_in_zones_s(
    points: Sequence[PreparedPoint],
    floors_bpm: Sequence[float] | None,
    *,
    invalid_hr: bool = False,
) -> tuple[int, ...] | None:
    """Count observed seconds in explicitly dated zones; warnings do not filter HR."""
    if invalid_hr or floors_bpm is None or not floors_bpm:
        return None
    if any(not math.isfinite(value) for value in floors_bpm) or any(
        right <= left for left, right in pairwise(floors_bpm)
    ):
        return None
    totals = [0] * (len(floors_bpm) + 1)
    for point in points[:-1]:
        if not point.timer_active:
            continue
        if point.heart_rate_bpm is None:
            continue
        zone = sum(point.heart_rate_bpm >= floor for floor in floors_bpm)
        totals[zone] += 1
    return tuple(totals)


def _average(values: Sequence[float | None]) -> float | None:
    available = [value for value in values if value is not None and math.isfinite(value)]
    return fmean(available) if available else None


def efficiency_factor(points: Sequence[PreparedPoint], *, invalid_hr: bool = False) -> float | None:
    """Mean sampled speed divided by mean sampled heart rate."""
    if invalid_hr:
        return None
    active = [point for point in points[:-1] if point.timer_active]
    speed = _average([point.speed_mps for point in active])
    heart_rate = _average([point.heart_rate_bpm for point in active])
    return None if speed is None or heart_rate is None or heart_rate <= 0 else speed / heart_rate


def pace_at_heart_rate_s_per_km(
    points: Sequence[PreparedPoint],
    lower_bpm: float = 140.0,
    upper_bpm: float = 150.0,
    *,
    invalid_hr: bool = False,
) -> float | None:
    """Return a per-run median pace in an inclusive HR band."""
    if invalid_hr or lower_bpm >= upper_bpm:
        return None
    paces = [
        1_000 / point.speed_mps
        for point in points[:-1]
        if point.timer_active
        and point.heart_rate_bpm is not None
        and lower_bpm <= point.heart_rate_bpm <= upper_bpm
        and point.speed_mps is not None
        and point.speed_mps > 0.5
    ]
    return None if not paces else median(paces)


def aerobic_decoupling_percent(
    points: Sequence[PreparedPoint],
    duration_s: float | None,
    *,
    is_steady_run: bool,
    invalid_hr: bool = False,
) -> float | None:
    """Compare first/second-half efficiency for annotated steady runs of one hour."""
    if not is_steady_run or invalid_hr or duration_s is None or duration_s < 3_600:
        return None
    halfway = duration_s / 2
    if not points:
        return None
    active = [point for point in points[:-1] if point.timer_active]
    first = [point for point in active if point.active_time_s < halfway]
    second = [point for point in active if point.active_time_s >= halfway]
    first_ef, second_ef = efficiency_factor(first), efficiency_factor(second)
    if first_ef is None or second_ef is None or first_ef <= 0:
        return None
    return (first_ef - second_ef) / first_ef * 100


def trimp(
    points: Sequence[PreparedPoint],
    inputs: AthleteInputs | None,
    *,
    invalid_hr: bool = False,
) -> float | None:
    """Calculate Banister TRIMP only when every required dated profile input exists."""
    if (
        invalid_hr
        or inputs is None
        or inputs.max_hr_bpm is None
        or inputs.resting_hr_bpm is None
        or inputs.sex_for_trimp not in {"female", "other"}
        or inputs.max_hr_bpm <= inputs.resting_hr_bpm
    ):
        return None
    coefficient, exponent = (0.86, 1.67) if inputs.sex_for_trimp == "female" else (0.64, 1.92)
    total = 0.0
    for point in points[:-1]:
        if not point.timer_active:
            continue
        heart_rate = point.heart_rate_bpm
        if heart_rate is None:
            continue
        relative_hr = (heart_rate - inputs.resting_hr_bpm) / (
            inputs.max_hr_bpm - inputs.resting_hr_bpm
        )
        relative_hr = min(1.0, max(0.0, relative_hr))
        total += (1 / 60) * relative_hr * coefficient * math.exp(exponent * relative_hr)
    return total


def grade_adjusted_pace_s_per_km(points: Sequence[PreparedPoint]) -> float | None:
    """Average Minetti-adjusted pace; elevation-derived values remain approximate."""
    adjusted_speeds: list[float] = []
    for point in points:
        if point.speed_mps is None or point.grade is None or point.speed_mps <= 0:
            continue
        grade = max(-0.45, min(0.45, point.grade))
        cost = (
            155.4 * grade**5
            - 30.4 * grade**4
            - 43.3 * grade**3
            + 46.3 * grade**2
            + 19.5 * grade
            + 3.6
        )
        adjusted_speeds.append(point.speed_mps * cost / 3.6)
    average_speed = _average(adjusted_speeds)
    return None if average_speed is None or average_speed <= 0 else 1_000 / average_speed


def race_predictions(
    source_distance_m: float,
    source_time_s: float,
    best_efforts: Sequence[BestEffort],
    target_distances_m: Sequence[float],
) -> tuple[RacePrediction, ...]:
    """Predict target times with Riegel, VDOT inversion and a best-effort CS fit."""
    if source_distance_m <= 0 or source_time_s <= 0:
        return ()
    vdot = _vdot(source_distance_m, source_time_s)
    critical_speed = _critical_speed(best_efforts)
    result: list[RacePrediction] = []
    for distance in target_distances_m:
        riegel = source_time_s * (distance / source_distance_m) ** 1.06
        vdot_time = None if vdot is None else _time_for_vdot(distance, vdot)
        cs_time = (
            None
            if critical_speed is None or distance <= critical_speed[1]
            else (distance - critical_speed[1]) / critical_speed[0]
        )
        result.append(RacePrediction(distance, riegel, vdot_time, cs_time))
    return tuple(result)


def _vo2(speed_m_per_min: float) -> float:
    return -4.60 + 0.182258 * speed_m_per_min + 0.000104 * speed_m_per_min**2


def _percent_vo2(time_min: float) -> float:
    return (
        0.8
        + 0.1894393 * math.exp(-0.012778 * time_min)
        + 0.2989558 * math.exp(-0.1932605 * time_min)
    )


def _vdot(distance_m: float, time_s: float) -> float | None:
    time_min = time_s / 60
    speed = distance_m / time_min
    fraction = _percent_vo2(time_min)
    return None if time_min <= 0 or fraction <= 0 else _vo2(speed) / fraction


def _time_for_vdot(distance_m: float, target_vdot: float) -> float | None:
    low, high = 1.0, 60_000.0
    if _vo2(distance_m / (low / 60)) / _percent_vo2(low / 60) < target_vdot:
        return None
    for _ in range(80):
        time_s = (low + high) / 2
        value = _vdot(distance_m, time_s)
        if value is None:
            return None
        if value > target_vdot:
            low = time_s
        else:
            high = time_s
    return (low + high) / 2


def _critical_speed(
    best_efforts: Sequence[BestEffort],
) -> tuple[float, float] | None:
    efforts = [
        (effort.duration_s, effort.distance_m)
        for effort in best_efforts
        if 180 <= effort.duration_s <= 1_200
    ]
    if len(efforts) < 2:
        return None
    mean_time = fmean(item[0] for item in efforts)
    mean_distance = fmean(item[1] for item in efforts)
    denominator = sum((time - mean_time) ** 2 for time, _ in efforts)
    if denominator == 0:
        return None
    speed = (
        sum((time - mean_time) * (distance - mean_distance) for time, distance in efforts)
        / denominator
    )
    d_prime = mean_distance - speed * mean_time
    return None if speed <= 0 or d_prime < 0 else (speed, d_prime)
