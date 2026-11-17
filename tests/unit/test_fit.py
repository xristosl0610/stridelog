"""Synthetic SDK round trips, normalization and deliberately conservative provenance."""

from dataclasses import replace
from datetime import date

import pytest
from garmin_fit_sdk import Encoder, Profile

from stridelog.fit import FitError, Sensor, classify_hr, decode_fit
from stridelog.synthetic import running_fit


def test_treadmill_pauses_laps_fractional_cadence_and_hr_dropout() -> None:
    parsed = decode_fit(running_fit(gps=False, paused=True, dropout=True, offset_s=7200))
    assert len(parsed.samples) == 6 and len(parsed.laps) == 2
    assert parsed.timer_time_s == 5 and parsed.elapsed_time_s == 6
    assert parsed.samples[0].lat_deg is None
    assert parsed.samples[0].heart_rate_bpm == 140
    assert parsed.samples[2].heart_rate_bpm is None
    assert parsed.samples[0].cadence_spm == parsed.avg_cadence_spm == 161
    assert parsed.laps[0].avg_cadence_spm == 161
    assert parsed.samples[0].altitude_m == pytest.approx(42.2)
    assert parsed.samples[0].speed_mps == 3
    assert parsed.end_utc_offset_s == 7200
    assert [event.event_type for event in parsed.events] == [
        "start",
        "stop_all",
        "start",
        "stop_all",
    ]
    assert parsed.samples[0].ts_utc.isoformat() == "2030-03-31T00:59:58+00:00"
    assert parsed.samples[3].ts_utc.isoformat() == "2030-03-31T01:00:01+00:00"
    # End offset is not silently assigned to the start across a DST transition.
    assert parsed.start_time_utc == parsed.samples[0].ts_utc


def test_enhanced_fields_win_and_semicircles_become_degrees() -> None:
    base = decode_fit(running_fit())
    encoder = Encoder()
    encoder.on_mesg(Profile["mesg_num"]["FILE_ID"], {"type": "activity"})
    encoder.on_mesg(
        Profile["mesg_num"]["RECORD"],
        {
            "timestamp": base.start_time_utc,
            "position_lat": 2**29,
            "position_long": -(2**29),
            "altitude": 12,
            "enhanced_altitude": 20,
            "speed": 2,
            "enhanced_speed": 3,
        },
    )
    encoder.on_mesg(
        Profile["mesg_num"]["SESSION"],
        {
            "sport": "running",
            "start_time": base.start_time_utc,
        },
    )
    sample = decode_fit(encoder.close()).samples[0]
    assert (sample.lat_deg, sample.lon_deg) == (45, -45)
    assert sample.altitude_m == 20 and sample.speed_mps == 3


def test_corrupt_crc_and_non_activity_rejected_with_fixed_codes() -> None:
    payload = bytearray(running_fit())
    payload[-1] ^= 1
    with pytest.raises(FitError, match=r"^fit_integrity$"):
        decode_fit(bytes(payload))
    encoder = Encoder()
    encoder.on_mesg(Profile["mesg_num"]["FILE_ID"], {"type": "activity"})
    with pytest.raises(FitError, match=r"^unsupported_sessions$"):
        decode_fit(encoder.close())


def test_hr_models_fallback_cutoff_conflicts_and_no_hr() -> None:
    parsed = decode_fit(running_fit())
    cutoff = date(2030, 3, 31)
    assert classify_hr(parsed, date(2030, 3, 30), cutoff) == ("unknown", "unknown")
    assert classify_hr(parsed, cutoff, cutoff) == ("armband", "user_date_rule")
    assert classify_hr(parsed, None, cutoff) == ("unknown", "unknown")
    strap = Sensor("antplus", "heart_rate", "garmin", None, "HRM-Pro")
    generic = Sensor("bluetooth_low_energy", "heart_rate", None, None, None)
    arm = Sensor("bluetooth_low_energy", "heart_rate", None, None, "COROS Heart Rate Monitor")
    assert classify_hr(replace(parsed, sensors=(strap,)), cutoff, cutoff) == ("chest_strap", "fit")
    assert classify_hr(replace(parsed, sensors=(arm,)), cutoff, None) == ("armband", "fit")
    for sensors in ((generic,), (strap, arm), (strap, generic)):
        classified = classify_hr(replace(parsed, sensors=sensors), cutoff, None)
        assert classified == ("unknown", "unknown")
    no_hr = replace(parsed, samples=tuple(replace(s, heart_rate_bpm=None) for s in parsed.samples))
    assert classify_hr(no_hr, cutoff, cutoff) == ("none", "fit")


def test_sensor_entries_deduplicated_and_identifiers_excluded() -> None:
    parsed = decode_fit(running_fit(model="COROS Heart Rate Monitor"))
    assert len(parsed.sensors) == 1
    assert parsed.sensors[0].device_type == "heart_rate"
    assert classify_hr(parsed, None, None) == ("armband", "fit")


def test_sdk_named_garmin_hrm_product_is_strap_evidence_without_a_product_name() -> None:
    parsed = decode_fit(running_fit())
    encoder = Encoder()
    encoder.on_mesg(Profile["mesg_num"]["FILE_ID"], {"type": "activity"})
    for _ in range(2):
        encoder.on_mesg(
            Profile["mesg_num"]["DEVICE_INFO"],
            {
                "device_index": 1,
                "source_type": "antplus",
                "device_type": 120,
                "manufacturer": "garmin",
                "product": 3299,
                "serial_number": 12345678,
            },
        )
    encoder.on_mesg(
        Profile["mesg_num"]["RECORD"],
        {
            "timestamp": parsed.start_time_utc,
            "heart_rate": 140,
        },
    )
    encoder.on_mesg(
        Profile["mesg_num"]["SESSION"],
        {
            "sport": "running",
            "start_time": parsed.start_time_utc,
        },
    )
    result = decode_fit(encoder.close())
    assert len(result.sensors) == 1
    assert result.sensors[0].product == "hrm_dual"
    assert "12345678" not in repr(result.sensors)
    assert classify_hr(result, date(2030, 3, 31), date(2030, 1, 1)) == ("chest_strap", "fit")
