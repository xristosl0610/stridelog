"""Explicit saved-JSON mappings; never guess unobserved units or date assignments."""

import math
from collections.abc import Mapping
from datetime import UTC, date, datetime
from typing import cast

from stridelog.errors import StridelogError


class MappingError(StridelogError):
    """Fixed-code schema error suitable for a private quality report."""


def object_fields(value: object) -> dict[str, object]:
    """Validate unknown JSON at the boundary, retaining only string keys."""
    if not isinstance(value, dict):
        raise MappingError("json_object_expected")
    fields = cast("dict[object, object]", value)
    if any(not isinstance(key, str) for key in fields):
        raise MappingError("json_key_invalid")
    return {str(key): item for key, item in fields.items()}


def optional_object(value: object) -> dict[str, object]:
    return {} if value is None else object_fields(value)


def numeric(fields: Mapping[str, object], key: str) -> float | None:
    value = fields.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise MappingError("json_number_invalid")
    try:
        result = float(value)
    except OverflowError:
        raise MappingError("json_number_invalid") from None
    if not math.isfinite(result):
        raise MappingError("json_number_invalid")
    return result


def label(fields: Mapping[str, object], key: str) -> str | None:
    value = fields.get(key)
    if value is not None and not isinstance(value, str):
        raise MappingError("json_string_invalid")
    return value


def start_offset(summary: Mapping[str, object], start: datetime) -> tuple[int | None, date | None]:
    """Use API's paired start times, never the computer's timezone or FIT end offset."""
    utc, local = summary.get("startTimeGMT"), summary.get("startTimeLocal")
    if utc is None or local is None:
        return None, None
    if not isinstance(utc, str) or not isinstance(local, str):
        raise MappingError("start_time_invalid")
    try:
        utc_time, local_time = datetime.fromisoformat(utc), datetime.fromisoformat(local)
    except ValueError:
        raise MappingError("start_time_invalid") from None
    if local_time.tzinfo is not None:
        raise MappingError("local_start_must_be_naive")
    utc_time = utc_time.replace(tzinfo=UTC) if utc_time.tzinfo is None else utc_time.astimezone(UTC)
    if abs((utc_time - start).total_seconds()) > 2:
        raise MappingError("fit_api_start_mismatch")
    offset = (local_time - utc_time.replace(tzinfo=None)).total_seconds()
    if not offset.is_integer() or abs(offset) > 14 * 3600:
        raise MappingError("start_offset_invalid")
    return int(offset), local_time.date()


def activity_metadata(
    summary: Mapping[str, object],
    details: Mapping[str, object],
) -> dict[str, object]:
    """Map confirmed names/event semantics and leave ambiguous cadence/stride units raw."""
    activity_type = optional_object(details.get("activityTypeDTO"))
    if not activity_type:
        activity_type = object_fields(summary.get("activityType"))
    kind = label(activity_type, "typeKey")
    if not kind:
        raise MappingError("activity_type_missing")
    event = optional_object(details.get("eventTypeDTO")) or optional_object(
        summary.get("eventType")
    )
    event_type = label(event, "typeKey")
    metrics: dict[str, float] = {}
    source = optional_object(details.get("summaryDTO"))
    for key in (
        "distance",
        "duration",
        "elapsedDuration",
        "movingDuration",
        "averageHR",
        "maxHR",
        "averageSpeed",
        "elevationGain",
        "elevationLoss",
        "vO2MaxValue",
        "aerobicTrainingEffect",
        "anaerobicTrainingEffect",
    ):
        value = numeric(source if key in source else summary, key)
        if value is not None:
            metrics[key] = value
    return {
        "name": label(details, "activityName") or label(summary, "activityName"),
        "activity_type": kind,
        "event_type": event_type,
        "is_race": event_type == "race",
        "garmin_metrics": metrics,
    }


def _one_day(value: object, day: date) -> dict[str, object]:
    if value is None:
        return {}
    if not isinstance(value, list):
        raise MappingError("daily_array_expected")
    entries = cast("list[object]", value)
    if not entries:
        return {}
    if len(entries) != 1:
        raise MappingError("ambiguous_daily_rows")
    row = object_fields(entries[0])
    for key in ("calendarDate", "date", "sleepDate"):
        stamp = row.get(key)
        if stamp is not None and stamp != day.isoformat():
            raise MappingError("daily_date_mismatch")
    return row


def wellness(dataset: str, payload: object, day: date) -> dict[str, object]:
    """Map only the verified one-day response families; unknown shapes fail explicitly."""
    if dataset == "daily":
        container = optional_object(payload)
        if container and "data" not in container:
            raise MappingError("daily_container_missing")
        row = _one_day(container.get("data"), day)
        if row and not {"heartRate", "movement", "stress", "bodyBattery"} & row.keys():
            raise MappingError("daily_fields_unverified")
        heart, movement = (
            optional_object(row.get("heartRate")),
            optional_object(row.get("movement")),
        )
        stress, battery = (
            optional_object(row.get("stress")),
            optional_object(row.get("bodyBattery")),
        )
        return {
            "resting_hr_bpm": numeric(heart, "restingValue"),
            "steps": numeric(movement, "steps"),
            "stress_avg": numeric(stress, "avgLevel"),
            "body_battery_high": numeric(battery, "maxValue"),
            "body_battery_low": numeric(battery, "minValue"),
        }
    if dataset == "sleep":
        row = _one_day(payload, day)
        if row and "sleepTimeSeconds" not in row:
            raise MappingError("sleep_fields_unverified")
        result: dict[str, object] = {
            target: numeric(row, source)
            for target, source in (
                ("duration_s", "sleepTimeSeconds"),
                ("deep_s", "deepSleepSeconds"),
                ("light_s", "lightSleepSeconds"),
                ("rem_s", "remSleepSeconds"),
                ("awake_s", "awakeSleepSeconds"),
            )
        }
        result["score"] = None
        return result
    if dataset == "hrv":
        if payload is not None and payload != []:
            raise MappingError("hrv_populated_schema_unverified")
        return {"last_night_avg_ms": None}
    raise MappingError("unsupported_wellness_dataset")


def zone_rows(payload: object) -> list[dict[str, object]]:
    if not isinstance(payload, list):
        raise MappingError("zones_array_expected")
    result: list[dict[str, object]] = []
    seen: set[str] = set()
    for item in cast("list[object]", payload):
        row = object_fields(item)
        sport = label(row, "sport")
        if not sport or sport in seen:
            raise MappingError("zones_sport_invalid")
        seen.add(sport)
        result.append(
            {
                "sport": sport,
                "training_method": label(row, "trainingMethod"),
                "floors_bpm": [numeric(row, f"zone{index}Floor") for index in range(1, 6)],
                "max_hr_bpm": numeric(row, "maxHeartRateUsed"),
                "resting_hr_bpm": numeric(row, "restingHeartRateUsed"),
                "lactate_threshold_hr_bpm": numeric(row, "lactateThresholdHeartRateUsed"),
            }
        )
    return result
