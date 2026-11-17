"""Privacy checks use filenames only, never real health data or credentials."""

import subprocess
import sys
from pathlib import Path

import pytest

HOOK = Path(__file__).resolve().parents[2] / "scripts" / "check_private_files.py"


@pytest.mark.parametrize(
    "filename",
    [
        "test.fit",
        "test.FIT",
        "archive.zip",
        "stridelog.sqlite",
        "stridelog.sqlite3-wal",
        "stridelog.db-shm",
        "route.gpx",
        "route.tcx",
        ".env",
        ".env.local",
        "raw/summary.json",
        "exports/history.csv",
        "data\\wellness.json",
        ".config/garmin/connect-personal-api-key",
    ],
)
def test_private_file_is_rejected(filename: str) -> None:
    result = subprocess.run(
        [sys.executable, str(HOOK), filename], capture_output=True, text=True, check=False
    )
    assert result.returncode == 1
    assert filename in result.stderr


def test_source_and_synthetic_factory_code_are_allowed() -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(HOOK),
            ".env.example",
            "tests/factories/activities.py",
            "openapi.json",
            "uv.lock",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert result.stderr == ""
