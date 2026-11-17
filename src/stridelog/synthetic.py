"""Deterministic FIT Encoder inputs for tests and the future offline demo."""

from datetime import UTC, datetime, timedelta

from garmin_fit_sdk import Encoder, Profile


def running_fit(
    *,
    gps: bool = True,
    paused: bool = False,
    dropout: bool = False,
    model: str | None = None,
    offset_s: int = 0,
    samples: int = 6,
) -> bytes:
    """Encode an invented running session; never reads any owner files."""
    start = datetime(2030, 3, 31, 0, 59, 58, tzinfo=UTC)
    encoder = Encoder()
    encoder.on_mesg(
        Profile["mesg_num"]["FILE_ID"],
        {
            "type": "activity",
            "manufacturer": "development",
            "product": 7,
            "time_created": start,
        },
    )
    if model is not None:
        encoder.on_mesg(
            Profile["mesg_num"]["DEVICE_INFO"],
            {
                "device_index": 1,
                "source_type": "bluetooth_low_energy",
                "device_type": 1,
                "product_name": model,
            },
        )
    encoder.on_mesg(
        Profile["mesg_num"]["EVENT"],
        {
            "timestamp": start,
            "event": "timer",
            "event_type": "start",
        },
    )
    for index in range(samples):
        encoder.on_mesg(
            Profile["mesg_num"]["RECORD"],
            {
                "timestamp": start + timedelta(seconds=index),
                "distance": index * 3.0,
                "enhanced_speed": 3.0,
                "enhanced_altitude": 42.2,
                "cadence": 80,
                "fractional_cadence": 0.5,
                **({"heart_rate": 140 + index} if not dropout or index not in (2, 3) else {}),
                **({"position_lat": 0, "position_long": index * 600} if gps else {}),
            },
        )
    if paused:
        for seconds, event_type in ((2, "stop_all"), (3, "start")):
            encoder.on_mesg(
                Profile["mesg_num"]["EVENT"],
                {
                    "timestamp": start + timedelta(seconds=seconds),
                    "event": "timer",
                    "event_type": event_type,
                    "timer_trigger": "manual",
                },
            )
    end = start + timedelta(seconds=samples)
    for low, high in ((0, samples // 2), (samples // 2, samples)):
        encoder.on_mesg(
            Profile["mesg_num"]["LAP"],
            {
                "start_time": start + timedelta(seconds=low),
                "timestamp": start + timedelta(seconds=high),
                "sport": "running",
                "total_distance": (high - low) * 3.0,
                "total_timer_time": high - low,
                "total_elapsed_time": high - low,
                "lap_trigger": "distance",
                "avg_cadence": 80,
                "avg_fractional_cadence": 0.5,
            },
        )
    encoder.on_mesg(
        Profile["mesg_num"]["SESSION"],
        {
            "start_time": start,
            "timestamp": end,
            "sport": "running",
            "total_distance": samples * 3.0,
            "total_timer_time": samples - int(paused),
            "total_elapsed_time": samples,
            "avg_heart_rate": 143,
            "avg_cadence": 80,
            "avg_fractional_cadence": 0.5,
        },
    )
    encoder.on_mesg(
        Profile["mesg_num"]["EVENT"],
        {
            "timestamp": end,
            "event": "timer",
            "event_type": "stop_all",
        },
    )
    encoder.on_mesg(
        Profile["mesg_num"]["ACTIVITY"],
        {
            "timestamp": end,
            "local_timestamp": int((end - datetime(1989, 12, 31, tzinfo=UTC)).total_seconds())
            + offset_s,
            "num_sessions": 1,
            "total_timer_time": samples - int(paused),
        },
    )
    return encoder.close()
