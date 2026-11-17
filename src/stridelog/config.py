"""Validated local settings; values must never be included in diagnostics."""

from datetime import date, datetime
from pathlib import Path

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def find_checkout_root(directory: Path) -> Path | None:
    """Find a source checkout even when the package is installed elsewhere."""
    return next(
        (parent for parent in (directory, *directory.parents) if (parent / ".git").exists()),
        None,
    )


REPOSITORY_ROOT = find_checkout_root(Path(__file__).resolve().parent)


class Settings(BaseSettings):
    """Read process settings before the ignored working-directory .env."""

    model_config = SettingsConfigDict(
        env_prefix="STRIDELOG_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        hide_input_in_errors=True,
        frozen=True,
    )

    data_dir: Path = Field(default_factory=lambda: Path.home() / ".stridelog")
    activity_lookback_days: int = Field(default=7, ge=0)
    wellness_lookback_days: int = Field(default=3, ge=0)
    request_interval_s: float = Field(default=1.0, ge=1.0, allow_inf_nan=False)
    running_activity_types: tuple[str, ...] = Field(
        default=("running", "trail_running", "treadmill_running", "track_running"),
        min_length=1,
    )
    api_key_expires_on: date | None = Field(default=None, repr=False)
    hr_armband_from: date | None = Field(default=None, repr=False)
    garmin_personal_api_key: SecretStr | None = Field(
        default=None, validation_alias="GARMIN_PERSONAL_API_KEY", repr=False
    )

    @field_validator("data_dir")
    @classmethod
    def private_data_directory(cls, value: Path) -> Path:
        """Resolve the storage boundary before any directory is created."""
        selected = value.expanduser().resolve()
        for root in (REPOSITORY_ROOT, find_checkout_root(Path.cwd().resolve())):
            if root is not None and selected.is_relative_to(root.resolve()):
                raise ValueError("Data storage must be outside the repository.")
        return selected

    @field_validator("api_key_expires_on", "hr_armband_from", mode="before")
    @classmethod
    def private_date(cls, value: object) -> date | None:
        """Require calendar dates, not timestamps or permissive date coercions."""
        if value is None or (isinstance(value, date) and not isinstance(value, datetime)):
            return value
        if isinstance(value, str):
            try:
                parsed = date.fromisoformat(value)
            except ValueError:
                pass
            else:
                if parsed.isoformat() == value:
                    return parsed
        raise ValueError("Use the exact YYYY-MM-DD format.")

    @field_validator("garmin_personal_api_key", mode="before")
    @classmethod
    def empty_key(cls, value: object) -> object:
        """Treat an unfilled example setting as missing, not as a credential."""
        return None if isinstance(value, str) and not value.strip() else value

    @field_validator("running_activity_types")
    @classmethod
    def activity_type_keys(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        """Accept explicit taxonomy keys, never empty or ambiguous fragments."""
        if any(not key or not key.isascii() or not key.replace("_", "").isalnum() for key in value):
            raise ValueError("Activity types must be nonempty ASCII taxonomy keys.")
        return value
