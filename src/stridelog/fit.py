"""Small typed FIT boundary. Decoded values are already scaled by the SDK."""

import math
import struct
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Literal, cast

from garmin_fit_sdk import Decoder, Stream

from stridelog.errors import StridelogError

PARSER_VERSION = 1
FIT_EPOCH = datetime(1989, 12, 31, tzinfo=UTC)
type Message = Mapping[str | int, object]
type HrSource = Literal["chest_strap", "armband", "wrist", "none", "unknown"]


class FitError(StridelogError):
    """Invalid or unsupported FIT; fixed codes must never contain file contents."""


def number(message: Message, key: str) -> float | None:
    """Accept finite numbers without silently accepting booleans or text."""
    value = message.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        raise FitError("invalid_numeric_field")
    return float(value)


def text(message: Message, key: str) -> str | None:
    """Normalize scalar enum/model metadata without storing device identifiers."""
    value = message.get(key)
    if value is None:
        return None
    if isinstance(value, str | int) and not isinstance(value, bool):
        return str(value)
    raise FitError("invalid_text_field")


def instant(message: Message, key: str) -> datetime:
    value = message.get(key)
    if not isinstance(value, datetime) or value.utcoffset() is None:
        raise FitError("missing_utc_timestamp")
    return value.astimezone(UTC)


def _preferred(message: Message, enhanced: str, legacy: str) -> float | None:
    value = number(message, enhanced)
    return number(message, legacy) if value is None else value


def _cadence(message: Message, prefix: str = "") -> float | None:
    whole = number(message, f"{prefix}cadence")
    fraction = number(message, f"{prefix}fractional_cadence")
    return None if whole is None else 2 * (whole + (fraction or 0))


@dataclass(frozen=True)
class Sample:
    ts_utc: datetime
    distance_m: float | None
    lat_deg: float | None
    lon_deg: float | None
    altitude_m: float | None
    speed_mps: float | None
    heart_rate_bpm: float | None
    cadence_spm: float | None


@dataclass(frozen=True)
class Lap:
    start_time_utc: datetime
    end_time_utc: datetime
    distance_m: float | None
    timer_time_s: float | None
    elapsed_time_s: float | None
    avg_hr_bpm: float | None
    avg_cadence_spm: float | None
    intensity: str | None
    trigger: str | None


@dataclass(frozen=True)
class Sensor:
    source_type: str | None
    device_type: str | None
    manufacturer: str | None
    product: str | None
    product_name: str | None

    @property
    def is_external_hr(self) -> bool:
        return self.source_type in {
            "ant",
            "antplus",
            "bluetooth_low_energy",
        } and self.device_type in {"heart_rate", "120", "1"}


@dataclass(frozen=True)
class Event:
    ts_utc: datetime
    event_type: str
    trigger: str | None


@dataclass(frozen=True)
class ParsedActivity:
    start_time_utc: datetime
    end_utc_offset_s: int | None
    distance_m: float | None
    timer_time_s: float | None
    elapsed_time_s: float | None
    avg_hr_bpm: float | None
    avg_cadence_spm: float | None
    samples: tuple[Sample, ...]
    laps: tuple[Lap, ...]
    sensors: tuple[Sensor, ...]
    events: tuple[Event, ...]


def _sample(message: Message) -> Sample:
    lat, lon = number(message, "position_lat"), number(message, "position_long")
    return Sample(
        instant(message, "timestamp"),
        number(message, "distance"),
        None if lat is None else lat * 180 / 2**31,
        None if lon is None else lon * 180 / 2**31,
        _preferred(message, "enhanced_altitude", "altitude"),
        _preferred(message, "enhanced_speed", "speed"),
        number(message, "heart_rate"),
        _cadence(message),
    )


def _lap(message: Message) -> Lap:
    return Lap(
        instant(message, "start_time"),
        instant(message, "timestamp"),
        number(message, "total_distance"),
        number(message, "total_timer_time"),
        number(message, "total_elapsed_time"),
        number(message, "avg_heart_rate"),
        _cadence(message, "avg_"),
        text(message, "intensity"),
        text(message, "lap_trigger"),
    )


def _sensor(message: Message) -> Sensor:
    kind = (
        text(message, "antplus_device_type")
        or text(message, "ble_device_type")
        or text(message, "device_type")
    )
    return Sensor(
        text(message, "source_type"),
        kind,
        text(message, "manufacturer"),
        text(message, "product") or text(message, "garmin_product"),
        text(message, "product_name"),
    )


def _end_offset(messages: Sequence[Message]) -> int | None:
    if not messages or messages[-1].get("local_timestamp") is None:
        return None
    last = messages[-1]
    local_seconds = number(last, "local_timestamp")
    if local_seconds is None:
        return None
    offset = FIT_EPOCH + timedelta(seconds=local_seconds) - instant(last, "timestamp")
    seconds = offset.total_seconds()
    if not seconds.is_integer() or abs(seconds) > 14 * 3600:
        raise FitError("invalid_local_offset")
    return int(seconds)


def decode_fit(payload: bytes) -> ParsedActivity:
    """Validate CRC on a separate stream; reject multisport rather than misassign records."""
    try:
        if not Decoder(Stream.from_byte_array(bytearray(payload))).check_integrity():
            raise FitError("fit_integrity")
        # SDK component expansion can replace a separately encoded enhanced value
        # with its legacy counterpart. Keep explicit fields and record HR intact.
        decoded, errors = Decoder(Stream.from_byte_array(bytearray(payload))).read(
            expand_components=False,
            merge_heart_rates=False,
        )
        if errors:
            raise FitError("fit_decode")
        # SDK TypedDicts omit unknown numeric message/field keys allowed by FIT.
        groups = cast("Mapping[str, Sequence[Message]]", decoded)
        sessions = groups.get("session_mesgs", [])
        if len(sessions) != 1 or sessions[0].get("sport") != "running":
            raise FitError("unsupported_sessions")
        session = sessions[0]
        samples = tuple(_sample(message) for message in groups.get("record_mesgs", []))
        if not samples:
            raise FitError("missing_records")
        events = tuple(
            Event(
                instant(message, "timestamp"),
                text(message, "event_type") or "unknown",
                text(message, "timer_trigger"),
            )
            for message in groups.get("event_mesgs", [])
            if message.get("event") == "timer"
        )
        return ParsedActivity(
            instant(session, "start_time"),
            _end_offset(groups.get("activity_mesgs", [])),
            number(session, "total_distance"),
            number(session, "total_timer_time"),
            number(session, "total_elapsed_time"),
            number(session, "avg_heart_rate"),
            _cadence(session, "avg_"),
            samples,
            tuple(_lap(message) for message in groups.get("lap_mesgs", [])),
            tuple(
                dict.fromkeys(_sensor(message) for message in groups.get("device_info_mesgs", []))
            ),
            events,
        )
    except ValueError, TypeError, OverflowError, IndexError, KeyError, struct.error:
        raise FitError("fit_decode") from None


def classify_hr(
    activity: ParsedActivity,
    local_day: date | None,
    armband_from: date | None,
) -> tuple[HrSource, str]:
    """Keep protocol category separate from wear location and label date assumptions."""
    if not any((sample.heart_rate_bpm or 0) > 0 for sample in activity.samples):
        return "none", "fit"
    known: set[HrSource] = set()
    ambiguous_external = False
    for sensor in activity.sensors:
        if not sensor.is_external_hr:
            continue
        model = (sensor.product_name or "").casefold()
        if model in {"hrm-pro", "hrm-pro plus", "hrm-dual", "hrm-run", "hrm-tri"}:
            known.add("chest_strap")
        elif model == "coros heart rate monitor":
            known.add("armband")
        else:
            ambiguous_external = True
    if len(known) > 1 or (known and ambiguous_external):
        return "unknown", "unknown"
    if known:
        return next(iter(known)), "fit"
    if local_day is not None and armband_from is not None and local_day >= armband_from:
        return "armband", "user_date_rule"
    return "unknown", "unknown"
