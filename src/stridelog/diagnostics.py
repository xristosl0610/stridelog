"""Local diagnostics; never authenticate or expose private configuration values."""

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from shutil import disk_usage

from stridelog.config import Settings
from stridelog.db.engine import database_status, initialize_database
from stridelog.errors import StridelogError


@dataclass(frozen=True)
class DoctorReport:
    """Safe diagnostic lines and readiness, without account-specific values."""

    lines: tuple[str, ...]
    ready: bool


def doctor_report(
    settings: Settings, *, initialize: bool = False, today: date | None = None
) -> DoctorReport:
    """Check configuration and local storage without contacting Garmin."""
    lines: list[str] = []
    key_file = Path.home() / ".config" / "garmin" / "connect-personal-api-key"
    key_present = settings.garmin_personal_api_key is not None or key_file.is_file()
    lines.append("API key: configured (not authenticated)" if key_present else "API key: missing")
    ready = key_present
    expires = settings.api_key_expires_on
    if expires is None:
        lines.append("API key expiration: not configured")
    else:
        remaining = (expires - (today or date.today())).days
        if remaining < 0:
            lines.append("API key expiration: expired")
            ready = False
        elif remaining == 0:
            lines.append("API key expiration: expires today")
        elif remaining <= 14:
            lines.append("API key expiration: warning (within 14 days)")
        else:
            lines.append("API key expiration: outside warning window")
    if initialize:
        initialize_database(settings.data_dir)
    snapshot = database_status(settings.data_dir)
    lines.append("Database: current" if snapshot is not None else "Database: not initialized")
    cache_present = (settings.data_dir / "bearer-token.json").is_file()
    lines.append(
        "Bearer cache: present (not validated)" if cache_present else "Bearer cache: absent"
    )
    existing = settings.data_dir
    while not existing.exists():
        if existing.parent == existing:
            raise StridelogError("Data volume is unavailable.")
        existing = existing.parent
    lines.append(f"Free disk space: {disk_usage(existing).free // (1024 * 1024)} MiB")
    return DoctorReport(tuple(lines), ready and snapshot is not None)
