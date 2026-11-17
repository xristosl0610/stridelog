"""Persistent sync bookkeeping, separate from rebuildable measurement data."""

from datetime import UTC, date, datetime
from uuid import uuid4

from sqlalchemy import CheckConstraint, Date, ForeignKey, Integer, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utc_now() -> str:
    """Represent operational instants unambiguously as ISO UTC text."""
    return datetime.now(UTC).isoformat()


class Base(DeclarativeBase):
    """Common SQLAlchemy metadata for operational migrations."""


class SyncRun(Base):
    """One attempted synchronization; error codes never contain raw exceptions."""

    __tablename__ = "sync_run"
    __table_args__ = (
        CheckConstraint("status IN ('running', 'succeeded', 'failed')", name="ck_sync_run_status"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: uuid4().hex)
    started_at_utc: Mapped[str] = mapped_column(String, default=utc_now)
    finished_at_utc: Mapped[str | None] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, default="running")
    error_code: Mapped[str | None] = mapped_column(String)


class SyncCursor(Base):
    """Last fully archived calendar day for a dataset."""

    __tablename__ = "sync_cursor"

    dataset: Mapped[str] = mapped_column(String, primary_key=True)
    through_date: Mapped[date] = mapped_column(Date)
    updated_at_utc: Mapped[str] = mapped_column(String, default=utc_now, onupdate=utc_now)


class RawFile(Base):
    """Checksum manifest for private archived files, with sync provenance."""

    __tablename__ = "raw_file"
    __table_args__ = (CheckConstraint("size_bytes >= 0", name="ck_raw_file_size"),)

    relative_path: Mapped[str] = mapped_column(String, primary_key=True)
    dataset: Mapped[str] = mapped_column(String)
    source_id: Mapped[str | None] = mapped_column(String)
    sha256: Mapped[str] = mapped_column(String(64))
    size_bytes: Mapped[int] = mapped_column(Integer)
    run_id: Mapped[str | None] = mapped_column(ForeignKey("sync_run.id"))
    updated_at_utc: Mapped[str] = mapped_column(String, default=utc_now, onupdate=utc_now)
