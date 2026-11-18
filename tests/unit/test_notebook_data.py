"""Notebook data loading is tested only with a synthetic local database."""

import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from stridelog.config import Settings
from stridelog.db.engine import database_engine, initialize_database
from stridelog.db.models import DailyWellness
from stridelog.notebook_data import read_table

pytestmark = pytest.mark.usefixtures("private_environment")


def test_notebook_loader_imports_outside_checkout_and_reads_synthetic_data(
    tmp_path: Path,
) -> None:
    data_dir = Settings().data_dir
    initialize_database(data_dir)
    engine = database_engine(data_dir)
    try:
        with Session(engine) as session, session.begin():
            session.add(
                DailyWellness(
                    local_date=date(2030, 1, 2),
                    resting_hr_bpm=50,
                    steps=1_234,
                    stress_avg=None,
                    body_battery_high=None,
                    body_battery_low=None,
                    raw_path="synthetic.json",
                    raw_sha256="a" * 64,
                )
            )
        rows = read_table(DailyWellness, ["local_date", "steps"])
        assert len(rows) == 1 and rows[0]["steps"] == 1_234
        script = (
            "from stridelog.notebook_data import read_table; "
            "from stridelog.db.models import DailyWellness; "
            "rows = read_table(DailyWellness, ['local_date', 'steps']); "
            "assert len(rows) == 1 and rows[0]['steps'] == 1234"
        )
        subprocess.run(
            [sys.executable, "-I", "-c", script],
            cwd=tmp_path,
            check=True,
            capture_output=True,
            text=True,
        )
    finally:
        engine.dispose()
