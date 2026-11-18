"""Display conversions for time, distance and running pace."""

import math
from collections.abc import Sequence


def format_duration(seconds: float) -> str:
    """Format nonnegative seconds as minutes:seconds or hours:minutes:seconds."""
    if not math.isfinite(seconds) or seconds < 0:
        raise ValueError("Duration must be a nonnegative finite number of seconds.")
    total = math.floor(seconds + 0.5)
    minutes, remainder = divmod(total, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{remainder:02d}"
    return f"{minutes}:{remainder:02d}"


def pace_seconds_per_km(speed_mps: float | None) -> float | None:
    """Convert positive speed to seconds per kilometre; stopped speed has no pace."""
    if speed_mps is None:
        return None
    if not math.isfinite(speed_mps) or speed_mps < 0:
        raise ValueError("Speed must be a nonnegative finite number.")
    return None if speed_mps == 0 else 1_000 / speed_mps


def distance_label(distance_m: float) -> str:
    """Format standard effort distances as readable labels."""
    if not math.isfinite(distance_m) or distance_m <= 0:
        raise ValueError("Distance must be a positive finite number of metres.")
    special = {
        1_609.344: "1 mile",
        16_093.44: "10 miles",
        21_097.5: "Half marathon",
        42_195.0: "Marathon",
    }
    if distance_m in special:
        return special[distance_m]
    return f"{distance_m / 1_000:g} km" if distance_m >= 1_000 else f"{distance_m:g} m"


def pace_ticks(paces_s_per_km: Sequence[float | None]) -> tuple[list[float], list[str]]:
    """Produce minute:second axis labels for positive available pace values."""
    available = [value for value in paces_s_per_km if value is not None]
    if not available:
        return [], []
    if any(not math.isfinite(value) or value <= 0 for value in available):
        raise ValueError("Pace must be a positive finite number of seconds per kilometre.")
    low, high = min(available), max(available)
    step = max(30, math.ceil((high - low) / 180) * 30)
    start = math.floor(low / step) * step
    stop = max(start + step, math.ceil(high / step) * step)
    values = [float(value) for value in range(start, stop + step, step)]
    return values, [format_duration(value) for value in values]
