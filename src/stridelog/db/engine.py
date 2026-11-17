"""SQLite setup, programmatic migrations and privacy-safe operational status."""

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import URL, Engine, create_engine, event, func, select
from sqlalchemy.orm import Session

from stridelog.db.models import RawFile, SyncRun
from stridelog.errors import StridelogError

DATABASE_NAME = "stridelog.sqlite"


def _migration_config() -> Config:
    configuration = Config()
    location = str(Path(__file__).parent / "migrations").replace("%", "%%")
    configuration.set_main_option("script_location", location)
    return configuration


def _connection_settings(connection: sqlite3.Connection, _record: object) -> None:
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute("PRAGMA busy_timeout=5000")


def database_engine(data_dir: Path) -> Engine:
    """Open only the fixed database target, never a linked file elsewhere."""
    target = data_dir / DATABASE_NAME
    if target.is_symlink() or target.resolve().parent != data_dir.resolve():
        raise StridelogError("Linked database target rejected.")
    engine = create_engine(
        URL.create("sqlite+pysqlite", database=str(target)),
        hide_parameters=True,
    )
    event.listen(engine, "connect", _connection_settings)
    return engine


def initialize_database(data_dir: Path) -> None:
    """Create protected-parent storage and upgrade operational tables to head."""
    data_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    engine = database_engine(data_dir)
    try:
        with engine.connect() as connection:
            mode = connection.exec_driver_sql("PRAGMA journal_mode=WAL").scalar_one()
            connection.commit()
            if mode != "wal":
                raise StridelogError("SQLite WAL mode could not be enabled.")
        with engine.begin() as connection:
            configuration = _migration_config()
            configuration.attributes["connection"] = connection
            command.upgrade(configuration, "head")
    finally:
        engine.dispose()


@dataclass(frozen=True)
class DatabaseStatus:
    """Aggregate operational diagnostics; never include private paths or IDs."""

    raw_files: int
    sync_runs: int
    last_run_status: str | None


def database_status(data_dir: Path) -> DatabaseStatus | None:
    """Return no snapshot when uninitialized; reject stale or unrelated schemas."""
    if not (data_dir / DATABASE_NAME).is_file():
        return None
    engine = database_engine(data_dir)
    try:
        with engine.connect() as connection:
            actual = set(MigrationContext.configure(connection).get_current_heads())
            expected = set(ScriptDirectory.from_config(_migration_config()).get_heads())
            if actual != expected:
                raise StridelogError("Database schema is not current; run doctor --initialize.")
        with Session(engine) as session:
            return DatabaseStatus(
                raw_files=session.execute(select(func.count()).select_from(RawFile)).scalar_one(),
                sync_runs=session.execute(select(func.count()).select_from(SyncRun)).scalar_one(),
                last_run_status=session.scalar(
                    select(SyncRun.status).order_by(SyncRun.started_at_utc.desc()).limit(1)
                ),
            )
    finally:
        engine.dispose()
