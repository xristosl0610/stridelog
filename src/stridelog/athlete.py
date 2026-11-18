"""Local, dated athlete inputs for analytics; values are never logged."""

import math
from datetime import date
from itertools import pairwise
from typing import Literal

from sqlalchemy.orm import Session

from stridelog.config import Settings
from stridelog.db.engine import database_engine, initialize_database
from stridelog.db.models import AthleteProfile
from stridelog.errors import StridelogError
from stridelog.ingest.locking import sync_lock


def save_profile(
    settings: Settings,
    effective_from: date,
    *,
    max_hr_bpm: float,
    resting_hr_bpm: float,
    threshold_hr_bpm: float | None,
    sex_for_trimp: Literal["female", "other"],
    hr_zone_floors_bpm: tuple[float, ...] | None,
) -> None:
    """Validate and atomically save a user-entered effective-dated profile."""
    for value in (max_hr_bpm, resting_hr_bpm, threshold_hr_bpm):
        if value is not None and (not math.isfinite(value) or not 30 <= value <= 240):
            raise StridelogError("Heart-rate profile values must be between 30 and 240 bpm.")
    if max_hr_bpm <= resting_hr_bpm:
        raise StridelogError("Maximum heart rate must exceed resting heart rate.")
    if hr_zone_floors_bpm is not None and (
        len(hr_zone_floors_bpm) != 5
        or any(not math.isfinite(value) or not 30 <= value <= 240 for value in hr_zone_floors_bpm)
        or any(right <= left for left, right in pairwise(hr_zone_floors_bpm))
    ):
        raise StridelogError("Zone floors must be five increasing values between 30 and 240 bpm.")
    with sync_lock(settings.data_dir):
        initialize_database(settings.data_dir)
        engine = database_engine(settings.data_dir)
        try:
            with Session(engine) as session, session.begin():
                session.merge(
                    AthleteProfile(
                        effective_from=effective_from,
                        max_hr_bpm=max_hr_bpm,
                        resting_hr_bpm=resting_hr_bpm,
                        threshold_hr_bpm=threshold_hr_bpm,
                        sex_for_trimp=sex_for_trimp,
                        hr_zone_floors_bpm=(
                            None if hr_zone_floors_bpm is None else list(hr_zone_floors_bpm)
                        ),
                    )
                )
        finally:
            engine.dispose()
