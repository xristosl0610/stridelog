"""Synthetic configuration, migration and local command acceptance checks."""

import os
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from typer.testing import CliRunner

from stridelog.cli import app
from stridelog.config import Settings, find_checkout_root
from stridelog.db.engine import (
    DATABASE_NAME,
    database_engine,
    database_status,
    initialize_database,
)
from stridelog.db.models import Base, RawFile, SyncCursor, SyncRun
from stridelog.diagnostics import doctor_report
from stridelog.errors import StridelogError

runner = CliRunner()


@pytest.fixture(autouse=True)
def private_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Prevent any test from inspecting the owner's .env or credential files."""

    def synthetic_checkout(_directory: Path) -> Path:
        return tmp_path / "checkout"

    for key in os.environ:
        if key.startswith("STRIDELOG_") or key == "GARMIN_PERSONAL_API_KEY":
            monkeypatch.delenv(key)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    monkeypatch.setattr("stridelog.config.REPOSITORY_ROOT", tmp_path / "checkout")
    monkeypatch.setattr("stridelog.config.find_checkout_root", synthetic_checkout)
    monkeypatch.setenv("STRIDELOG_DATA_DIR", str(tmp_path / "private"))
    monkeypatch.setenv("GARMIN_PERSONAL_API_KEY", "synthetic-key-not-a-credential")


def test_dotenv_precedence_and_private_dates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("GARMIN_PERSONAL_API_KEY")
    (tmp_path / ".env").write_text(
        "GARMIN_PERSONAL_API_KEY=synthetic-dotenv-key\n"
        "STRIDELOG_ACTIVITY_LOOKBACK_DAYS=9\n"
        "STRIDELOG_API_KEY_EXPIRES_ON=2030-02-28\n"
        "STRIDELOG_HR_ARMBAND_FROM=2025-03-04\n",
        encoding="utf-8",
    )
    settings = Settings()
    assert settings.garmin_personal_api_key is not None
    assert settings.garmin_personal_api_key.get_secret_value() == "synthetic-dotenv-key"
    assert settings.activity_lookback_days == 9
    assert settings.api_key_expires_on == date(2030, 2, 28)
    assert settings.hr_armband_from == date(2025, 3, 4)
    assert "synthetic-dotenv-key" not in repr(settings)
    assert "2030-02-28" not in repr(settings)
    assert "2025-03-04" not in repr(settings)
    monkeypatch.setenv("STRIDELOG_ACTIVITY_LOOKBACK_DAYS", "11")
    assert Settings().activity_lookback_days == 11


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("STRIDELOG_API_KEY_EXPIRES_ON", "20300102"),
        ("STRIDELOG_HR_ARMBAND_FROM", "2030-W01-1"),
        ("STRIDELOG_API_KEY_EXPIRES_ON", "2030-02-30"),
        ("STRIDELOG_HR_ARMBAND_FROM", "2030-01-02T00:00:00Z"),
        ("STRIDELOG_REQUEST_INTERVAL_S", "0.9"),
        ("STRIDELOG_REQUEST_INTERVAL_S", "nan"),
        ("STRIDELOG_REQUEST_INTERVAL_S", "inf"),
        ("STRIDELOG_ACTIVITY_LOOKBACK_DAYS", "-1"),
    ],
)
def test_invalid_settings_are_sanitized(
    field: str, value: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(field, value)
    with pytest.raises(ValidationError):
        Settings()
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 1
    assert "Invalid configuration fields:" in result.output
    assert value not in result.output
    assert "synthetic-key" not in result.output


def test_storage_inside_checkout_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("STRIDELOG_DATA_DIR", str(tmp_path / "checkout" / "data"))
    result = runner.invoke(app, ["doctor", "--initialize"])
    assert result.exit_code == 1
    assert "data_dir" in result.output
    assert str(tmp_path) not in result.output
    assert not (tmp_path / "checkout").exists()


def test_installed_wheel_still_rejects_storage_in_working_checkout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    checkout = tmp_path / "checkout"
    (checkout / ".git").mkdir(parents=True)
    monkeypatch.chdir(checkout)
    monkeypatch.setattr("stridelog.config.REPOSITORY_ROOT", None)
    monkeypatch.setattr("stridelog.config.find_checkout_root", find_checkout_root)
    monkeypatch.setenv("STRIDELOG_DATA_DIR", str(checkout / "data"))
    with pytest.raises(ValidationError):
        Settings()
    assert not (checkout / "data").exists()


def test_migration_persistence_integrity_and_reinitialization(tmp_path: Path) -> None:
    data_dir = Settings().data_dir
    assert database_status(data_dir) is None
    initialize_database(data_dir)
    engine = database_engine(data_dir)
    try:
        with engine.connect() as connection:
            assert connection.exec_driver_sql("PRAGMA journal_mode").scalar_one() == "wal"
            assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar_one() == 1
            assert connection.exec_driver_sql("PRAGMA busy_timeout").scalar_one() == 5000
            assert compare_metadata(MigrationContext.configure(connection), Base.metadata) == []
        with Session(engine) as session:
            run = SyncRun(status="succeeded")
            session.add(run)
            session.flush()
            assert datetime.fromisoformat(run.started_at_utc).utcoffset() == timedelta(0)
            session.add(
                RawFile(
                    relative_path="raw/synthetic.json",
                    dataset="daily",
                    sha256="0" * 64,
                    size_bytes=2,
                    run_id=run.id,
                )
            )
            session.add(SyncCursor(dataset="daily", through_date=date(2025, 1, 1)))
            session.commit()
        with engine.begin() as connection, pytest.raises(IntegrityError):
            connection.execute(
                text("INSERT INTO sync_run (id, started_at_utc, status) VALUES ('x', 'x', 'bad')")
            )
        with Session(engine) as session, pytest.raises(IntegrityError):
            session.add(
                RawFile(
                    relative_path="bad",
                    dataset="daily",
                    sha256="0" * 64,
                    size_bytes=0,
                    run_id="nonexistent",
                )
            )
            session.commit()
    finally:
        engine.dispose()
    initialize_database(data_dir)
    snapshot = database_status(data_dir)
    assert snapshot is not None
    assert (snapshot.raw_files, snapshot.sync_runs, snapshot.last_run_status) == (1, 1, "succeeded")
    assert (data_dir / DATABASE_NAME).is_file()
    assert not (tmp_path / "checkout").exists()


def test_doctor_and_status_require_initialized_storage_without_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbid_network(*_args: object, **_kwargs: object) -> None:
        pytest.fail("Local diagnostics must not access the network")

    monkeypatch.setattr("socket.socket.connect", forbid_network)
    settings = Settings()
    missing = runner.invoke(app, ["doctor"])
    assert missing.exit_code == 1
    assert "Database: not initialized" in missing.output
    assert not settings.data_dir.exists()
    assert runner.invoke(app, ["status"]).exit_code == 1
    initialized = runner.invoke(app, ["doctor", "--initialize"])
    assert initialized.exit_code == 0, initialized.output
    assert "Database: current" in initialized.output
    assert "not authenticated" in initialized.output
    assert "Bearer cache: absent" in initialized.output
    status = runner.invoke(app, ["status"])
    assert status.exit_code == 0
    assert "Archived files: 0" in status.output
    assert "Sync runs: 0" in status.output
    assert "Last sync: never" in status.output
    assert "synthetic" not in initialized.output + status.output
    assert str(settings.data_dir) not in initialized.output + status.output


@pytest.mark.parametrize(
    ("remaining", "message", "ready"),
    [
        (15, "outside warning window", True),
        (14, "warning (within 14 days)", True),
        (1, "warning (within 14 days)", True),
        (0, "expires today", True),
        (-1, "expired", False),
    ],
)
def test_expiration_boundaries(
    remaining: int, message: str, ready: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    today = date(2030, 5, 20)
    monkeypatch.setenv(
        "STRIDELOG_API_KEY_EXPIRES_ON", (today + timedelta(days=remaining)).isoformat()
    )
    report = doctor_report(Settings(), initialize=True, today=today)
    assert report.ready is ready
    assert message in "\n".join(report.lines)
    assert today.isoformat() not in "\n".join(report.lines)


def test_missing_key_and_existing_private_key_file(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GARMIN_PERSONAL_API_KEY", "")
    settings = Settings()
    missing = doctor_report(settings, initialize=True)
    assert not missing.ready
    assert "API key: missing" in missing.lines
    key_file = Path.home() / ".config" / "garmin" / "connect-personal-api-key"
    key_file.parent.mkdir(parents=True)
    key_file.write_text("synthetic-key", encoding="utf-8")
    (settings.data_dir / "bearer-token.json").write_text("{}", encoding="utf-8")
    assert doctor_report(settings).ready


def test_unknown_revision_and_corrupt_database_errors_are_private() -> None:
    settings = Settings()
    initialize_database(settings.data_dir)
    engine = database_engine(settings.data_dir)
    try:
        with engine.begin() as connection:
            connection.execute(text("UPDATE alembic_version SET version_num = 'unknown'"))
    finally:
        engine.dispose()
    result = runner.invoke(app, ["status"])
    assert result.exit_code == 1
    assert "schema is not current" in result.output
    target = settings.data_dir / DATABASE_NAME
    target.write_bytes(b"synthetic-not-a-database")
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 1
    assert "Local storage operation failed" in result.output
    assert str(settings.data_dir) not in result.output
    assert "synthetic" not in result.output


def test_direct_timestamp_dates_are_rejected() -> None:
    with pytest.raises(ValidationError):
        Settings(api_key_expires_on=datetime(2030, 1, 1, tzinfo=UTC))
    assert Settings(api_key_expires_on=date(2030, 1, 1)).api_key_expires_on == date(2030, 1, 1)


def test_database_target_cannot_be_a_symbolic_link(tmp_path: Path) -> None:
    data_dir = Settings().data_dir
    data_dir.mkdir()
    target = tmp_path / "other.sqlite"
    target.touch()
    try:
        (data_dir / DATABASE_NAME).symlink_to(target)
    except OSError:
        pytest.skip("Creating symlinks requires platform permission")
    with pytest.raises(StridelogError, match="Linked database"):
        initialize_database(data_dir)
