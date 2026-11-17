"""Run synthetic notebook checks in the isolated FIT discovery environment."""

import json
import unittest
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import cast
from zipfile import ZipFile

from garmin_fit_sdk import Encoder, Profile

ROOT = Path(__file__).resolve().parents[1]
Inspector = Callable[[Path, Path], dict[str, object]]


def _load_inspector() -> Inspector:
    notebook = json.loads((ROOT / "notebooks" / "01_fit_discovery.ipynb").read_text("utf-8"))
    cells = [cell for cell in notebook["cells"] if cell["cell_type"] == "code"]
    namespace: dict[str, object] = {}
    for cell in cells[:2]:
        exec(compile("".join(cell["source"]), "<notebook helpers>", "exec"), namespace)  # noqa: S102
    return cast(Inspector, namespace["_inspect_fit"])


def _payload() -> bytes:
    start = datetime(2030, 1, 2, tzinfo=UTC)
    encoder = Encoder()
    encoder.on_mesg(
        Profile["mesg_num"]["FILE_ID"],
        {"type": "activity", "manufacturer": "development", "product": 7, "time_created": start},
    )
    for source, device in ((0, 120), (1, 120), (3, 1)):
        encoder.on_mesg(
            Profile["mesg_num"]["DEVICE_INFO"],
            {"source_type": source, "device_type": device, "serial_number": 12345678},
        )
    for seconds in (0, 1, 3):
        encoder.on_mesg(
            Profile["mesg_num"]["RECORD"],
            {
                "timestamp": start + timedelta(seconds=seconds),
                "heart_rate": 191,
                "position_lat": 987654321,
                "distance": seconds * 3.25,
            },
        )
    return encoder.close()


class FitDiscoveryChecks(unittest.TestCase):
    """Exercise projection and input boundaries without real activity data."""

    def setUp(self) -> None:
        (ROOT / ".tools").mkdir(exist_ok=True)
        self.scratch = TemporaryDirectory(prefix="fit-check-", dir=ROOT / ".tools")
        self.addCleanup(self.scratch.cleanup)
        directory = Path(self.scratch.name)
        self.repository = directory / "repository"
        self.repository.mkdir()
        self.sample = directory / "private-synthetic.fit"
        self.sample.write_bytes(_payload())
        self.inspect = _load_inspector()

    def test_protocol_aliases_preserve_raw_ant_and_do_not_classify_source(self) -> None:
        report = self.inspect(self.sample, self.repository)
        self.assertEqual(
            report["sensor_models_not_identifiers"],
            [
                {"source_type": "ant", "device_type": 120, "ant_device_type": 120},
                {
                    "source_type": "antplus",
                    "device_type": 120,
                    "antplus_device_type": "heart_rate",
                },
                {
                    "source_type": "bluetooth_low_energy",
                    "device_type": 1,
                    "ble_device_type": "heart_rate",
                },
            ],
        )
        self.assertIs(report["hr_values_present"], True)
        self.assertEqual(report["sampling"], "variable_intervals")
        self.assertEqual(report["source_classification"], "not_performed")

    def test_zip_parity_and_private_value_projection(self) -> None:
        zipped = self.sample.with_suffix(".zip")
        with ZipFile(zipped, "w") as archive:
            archive.writestr("private-member-name.fit", self.sample.read_bytes())
        report = self.inspect(zipped, self.repository)
        self.assertEqual(report, self.inspect(self.sample, self.repository))
        rendered = json.dumps(report)
        for value in ("private-member-name", "12345678", "987654321", "2030-01-02", "191"):
            with self.subTest(value=value):
                self.assertNotIn(value, rendered)
        self.assertNotIn(str(self.sample.parent), rendered)

    def test_corrupt_input_does_not_produce_a_report(self) -> None:
        data = bytearray(self.sample.read_bytes())
        data[-1] ^= 1
        self.sample.write_bytes(data)
        with self.assertRaisesRegex(ValueError, "integrity validation failed"):
            self.inspect(self.sample, self.repository)

    def test_in_repository_sample_is_rejected(self) -> None:
        inside = self.repository / "sample.fit"
        inside.write_bytes(self.sample.read_bytes())
        with self.assertRaisesRegex(ValueError, "outside the repository"):
            self.inspect(inside, self.repository)


if __name__ == "__main__":
    unittest.main()
