"""Fake-source acceptance: archive safety, lookbacks, interruption and CLI dry-run."""

import hashlib
import json
from collections.abc import Generator
from contextlib import AbstractContextManager, contextmanager
from datetime import date
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile, ZipInfo

import pytest
from pydantic import JsonValue
from sqlalchemy import select
from sqlalchemy.orm import Session
from typer.testing import CliRunner

from stridelog.cli import app
from stridelog.config import Settings
from stridelog.db.engine import database_engine, initialize_database
from stridelog.db.models import RawFile, SyncCursor, SyncRun
from stridelog.errors import StridelogError
from stridelog.ingest.archive import RawStore
from stridelog.ingest.locking import sync_lock
from stridelog.ingest.sync import synchronize
from stridelog.synthetic import running_fit

pytestmark = pytest.mark.usefixtures("private_environment")


def original_zip() -> bytes:
    """ZIP contents are an SDK-encoded synthetic activity, never owner data."""
    buffer = BytesIO()
    with ZipFile(buffer, "w") as archive:
        archive.writestr(
            ZipInfo("synthetic.fit", date_time=(2025, 1, 1, 0, 0, 0)),
            running_fit(),
        )
    return buffer.getvalue()


def activity(identifier: int, day: int, kind: str = "running") -> dict[str, JsonValue]:
    return {
        "activityId": identifier,
        "startTimeLocal": f"2025-01-{day:02d} 10:00:00",
        "activityType": {"typeKey": kind},
    }


class FakeSource:
    """Small-page source with controllable edits and failures."""

    def __init__(self) -> None:
        self.rows = [activity(1, 1), activity(2, 2, "trail_running"), activity(3, 2, "cycling")]
        self.detail_calls: list[str] = []
        self.original_calls: list[str] = []
        self.wellness_calls: list[tuple[str, date]] = []
        self.offsets: list[int] = []
        self.fail_original: str | None = None
        self.fail_wellness: tuple[str, date] | None = None
        self.revision = 0
        self.zip_bytes = original_zip()

    @contextmanager
    def open(self) -> Generator[FakeSource]:
        yield self

    def activity_types(self) -> JsonValue:
        return [{"key": "running"}, {"key": "trail_running", "parent": "running"}]

    def activities(self, start: date, end: date, offset: int) -> JsonValue:
        self.offsets.append(offset)
        rows: list[JsonValue] = []
        for row in self.rows:
            stamp = row["startTimeLocal"]
            if isinstance(stamp, str) and start <= date.fromisoformat(stamp[:10]) <= end:
                rows.append(row)
        return rows[offset : offset + 2]

    def details(self, activity_id: str) -> JsonValue:
        self.detail_calls.append(activity_id)
        return {"activityId": activity_id, "synthetic_revision": self.revision}

    def original(self, activity_id: str) -> bytes:
        self.original_calls.append(activity_id)
        if self.fail_original == activity_id:
            raise StridelogError("Synthetic original interruption.")
        return self.zip_bytes

    def wellness(self, dataset: str, day: date) -> JsonValue:
        self.wellness_calls.append((dataset, day))
        if self.fail_wellness == (dataset, day):
            raise StridelogError("Synthetic wellness interruption.")
        if dataset == "daily":
            return {"data": [], "revision": self.revision}
        return [] if dataset == "sleep" else None

    def zones(self) -> JsonValue:
        return [{"sport": "running"}]


def test_repeat_sync_is_idempotent_and_archives_only_runs() -> None:
    settings, source = Settings(), FakeSource()
    first = synchronize(settings, source.open, today=date(2025, 1, 2))
    paths = {path.relative_to(settings.data_dir) for path in settings.data_dir.rglob("*.json")}
    assert first.downloaded_originals == 2
    assert source.offsets == [0, 2, 3]
    assert source.detail_calls == ["1", "2"]
    assert not (settings.data_dir / "raw" / "activities" / "2025" / "3").exists()
    second = synchronize(settings, source.open, today=date(2025, 1, 2))
    assert second.updated_documents == second.downloaded_originals == 0
    assert source.original_calls == ["1", "2"]
    assert {
        path.relative_to(settings.data_dir) for path in settings.data_dir.rglob("*.json")
    } == paths
    assert (
        json.loads(
            (
                settings.data_dir / "raw" / "wellness" / "hrv" / "2025-01-01_2025-01-01.json"
            ).read_text()
        )
        is None
    )
    engine = database_engine(settings.data_dir)
    try:
        with Session(engine) as session:
            assert list(session.scalars(select(SyncRun.status))) == ["succeeded", "succeeded"]
            for entry in session.scalars(select(RawFile)):
                assert (
                    hashlib.sha256(
                        (settings.data_dir / entry.relative_path).read_bytes()
                    ).hexdigest()
                    == entry.sha256
                )
            assert {
                item.dataset: item.through_date for item in session.scalars(select(SyncCursor))
            } == {name: date(2025, 1, 2) for name in ("activities", "daily", "sleep", "hrv")}
    finally:
        engine.dispose()


def test_interrupted_activity_resumes_without_redownloading_completed_originals() -> None:
    settings, source = Settings(), FakeSource()
    source.fail_original = "2"
    with pytest.raises(StridelogError, match="interruption"):
        synchronize(settings, source.open, today=date(2025, 1, 20))
    source.fail_original = None
    synchronize(settings, source.open, today=date(2025, 1, 20))
    assert source.original_calls == ["1", "2", "2"]
    assert source.detail_calls.count("1") == 1
    engine = database_engine(settings.data_dir)
    try:
        with Session(engine) as session:
            assert list(session.scalars(select(SyncRun.status))) == ["failed", "succeeded"]
            assert session.get(SyncCursor, "activities") is not None
    finally:
        engine.dispose()


def test_wellness_daily_checkpoint_and_lookback_resume() -> None:
    settings, source = Settings(), FakeSource()
    source.fail_wellness = ("daily", date(2025, 1, 3))
    with pytest.raises(StridelogError):
        synchronize(settings, source.open, today=date(2025, 1, 5))
    engine = database_engine(settings.data_dir)
    try:
        with Session(engine) as session:
            daily = session.get(SyncCursor, "daily")
            assert daily is not None and daily.through_date == date(2025, 1, 2)
            assert session.get(SyncCursor, "sleep") is None
    finally:
        engine.dispose()
    source.fail_wellness = None
    synchronize(settings, source.open, today=date(2025, 1, 5))
    assert all(
        (dataset, date(2025, 1, day)) in source.wellness_calls
        for dataset in ("daily", "sleep", "hrv")
        for day in range(1, 6)
    )


def test_explicit_older_reconciliation_preserves_json_history_and_originals() -> None:
    settings, source = Settings(), FakeSource()
    synchronize(settings, source.open, today=date(2025, 1, 2))
    source.detail_calls.clear()
    source.revision = 1
    synchronize(settings, source.open, today=date(2025, 1, 20))
    assert source.detail_calls == []
    synchronize(settings, source.open, since=date(2025, 1, 1), today=date(2025, 1, 20))
    assert source.detail_calls == ["1", "2"]
    assert source.original_calls == ["1", "2"]
    details = settings.data_dir / "raw" / "activities" / "2025" / "1" / "details.json"
    assert json.loads(details.read_text())["synthetic_revision"] == 1
    versions = list(details.with_name("details.json.versions").glob("*.json"))
    assert len(versions) == 2
    assert {json.loads(path.read_text())["synthetic_revision"] for path in versions} == {0, 1}


def test_lock_conflict_and_recovery() -> None:
    settings = Settings()
    with sync_lock(settings.data_dir), pytest.raises(StridelogError, match="Another sync"):
        synchronize(settings, FakeSource().open, today=date(2025, 1, 1))
    synchronize(settings, FakeSource().open, today=date(2025, 1, 2))


def test_stale_running_log_is_recovered_after_process_lock_released() -> None:
    settings = Settings()
    initialize_database(settings.data_dir)
    engine = database_engine(settings.data_dir)
    try:
        with Session(engine) as session, session.begin():
            session.add(SyncRun(id="synthetic-stale"))
        synchronize(settings, FakeSource().open, today=date(2025, 1, 2))
        with Session(engine) as session:
            previous = session.get(SyncRun, "synthetic-stale")
            assert previous is not None
            assert previous.status == "failed" and previous.error_code == "interrupted"
    finally:
        engine.dispose()


def test_original_adopted_after_file_durable_but_manifest_rolled_back() -> None:
    settings = Settings()
    initialize_database(settings.data_dir)
    engine = database_engine(settings.data_dir)
    try:
        with Session(engine) as session, session.begin():
            session.add(SyncRun(id="synthetic-run"))
        with Session(engine) as session:
            store = RawStore(settings.data_dir, session, "synthetic-run")
            store.write_original("raw/original.zip", original_zip(), "1")
            session.rollback()
        with Session(engine) as session, session.begin():
            store = RawStore(settings.data_dir, session, "synthetic-run")
            assert store.has_original("raw/original.zip", "1")
        with Session(engine) as session:
            assert session.get(RawFile, "raw/original.zip") is not None
    finally:
        engine.dispose()


def test_atomic_replace_failure_preserves_previous_current_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings()
    initialize_database(settings.data_dir)
    engine = database_engine(settings.data_dir)
    target = settings.data_dir / "raw" / "current.json"
    try:
        with Session(engine) as session, session.begin():
            session.add(SyncRun(id="synthetic-run"))
            session.flush()
            RawStore(settings.data_dir, session, "synthetic-run").write_json(
                "raw/current.json", {"revision": 0}, "daily", "synthetic"
            )

        def fail_replace(_source: Path, _target: Path) -> None:
            raise OSError("Synthetic disk failure.")

        monkeypatch.setattr("stridelog.storage.os.replace", fail_replace)
        with Session(engine) as session, pytest.raises(OSError):
            RawStore(settings.data_dir, session, "synthetic-run").write_json(
                "raw/current.json", {"revision": 1}, "daily", "synthetic"
            )
        assert json.loads(target.read_text()) == {"revision": 0}
        assert not list(settings.data_dir.rglob(".tmp-*"))
    finally:
        engine.dispose()


@pytest.mark.parametrize("relative", ["../outside.json", "/absolute.json", "x\\y", "C:outside"])
def test_archive_rejects_escaping_paths(relative: str) -> None:
    settings = Settings()
    initialize_database(settings.data_dir)
    engine = database_engine(settings.data_dir)
    try:
        with Session(engine) as session, pytest.raises(StridelogError, match="archive path"):
            RawStore(settings.data_dir, session, "unused").write_json(relative, {}, "daily", "x")
    finally:
        engine.dispose()


def test_dry_run_does_not_create_storage_or_contact_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden(*_args: object, **_kwargs: object) -> None:
        pytest.fail("Dry run must not open the source")

    monkeypatch.setattr("stridelog.cli.open_personal_source", forbidden)
    settings = Settings()
    result = CliRunner().invoke(app, ["sync", "--dry-run", "--since", "2025-01-01"])
    assert result.exit_code == 0, result.output
    assert "No network or storage writes" in result.output
    assert not settings.data_dir.exists()
    for invalid in ("20250101", "2025-W01-1", "2999-01-01", "private-invalid-date"):
        result = CliRunner().invoke(app, ["sync", "--dry-run", "--since", invalid])
        assert result.exit_code == 1
        assert invalid not in result.output


def test_malformed_collection_configuration_is_sanitized(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("STRIDELOG_RUNNING_ACTIVITY_TYPES", "private-invalid-json")
    result = CliRunner().invoke(app, ["sync", "--dry-run"])
    assert result.exit_code == 1
    assert "Invalid configuration format" in result.output
    assert "private-invalid-json" not in result.output


def test_interrupted_json_recovers_without_silently_replacing_corruption() -> None:
    settings = Settings()
    initialize_database(settings.data_dir)
    engine = database_engine(settings.data_dir)
    try:
        with Session(engine) as session, session.begin():
            session.add(SyncRun(id="synthetic-run"))
            session.flush()
            RawStore(settings.data_dir, session, "synthetic-run").write_json(
                "raw/current.json", {"revision": 0}, "daily", "x"
            )
        with Session(engine) as session:
            RawStore(settings.data_dir, session, "synthetic-run").write_json(
                "raw/current.json", {"revision": 1}, "daily", "x"
            )
            session.rollback()
        with Session(engine) as session, session.begin():
            assert RawStore(settings.data_dir, session, "synthetic-run").write_json(
                "raw/current.json", {"revision": 1}, "daily", "x"
            )
        target = settings.data_dir / "raw" / "current.json"
        target.write_bytes(b"synthetic-corruption")
        with Session(engine) as session, pytest.raises(StridelogError, match="checksum"):
            RawStore(settings.data_dir, session, "synthetic-run").write_json(
                "raw/current.json", {"revision": 1}, "daily", "x"
            )
        assert target.read_bytes() == b"synthetic-corruption"
    finally:
        engine.dispose()


def test_immutable_original_and_checksum_are_enforced() -> None:
    settings = Settings()
    initialize_database(settings.data_dir)
    engine = database_engine(settings.data_dir)
    try:
        with Session(engine) as session, session.begin():
            session.add(SyncRun(id="synthetic-run"))
            session.flush()
            store = RawStore(settings.data_dir, session, "synthetic-run")
            store.write_original("raw/original.zip", original_zip(), "1")
            with pytest.raises(StridelogError, match="valid ZIP"):
                store.write_original("raw/invalid.zip", b"not-a-zip", "2")
            changed = BytesIO()
            with ZipFile(changed, "w") as archive:
                archive.writestr("other.fit", b"different-synthetic-bytes")
            with pytest.raises(StridelogError, match="Immutable"):
                store.write_original("raw/original.zip", changed.getvalue(), "1")
        target = settings.data_dir / "raw" / "original.zip"
        target.write_bytes(changed.getvalue())
        with Session(engine) as session, pytest.raises(StridelogError, match="checksum"):
            RawStore(settings.data_dir, session, "synthetic-run").has_original(
                "raw/original.zip", "1"
            )
    finally:
        engine.dispose()


@pytest.mark.parametrize("malformed", ["identifier", "local_date", "page", "duplicate"])
def test_malformed_activity_pages_fail_without_advancing_cursor(malformed: str) -> None:
    class MalformedSource(FakeSource):
        def activities(self, start: date, end: date, offset: int) -> JsonValue:
            if malformed == "page":
                return {"not": "an array"}
            row = activity(1, 1)
            if malformed == "identifier":
                row["activityId"] = "../private"
            elif malformed == "local_date":
                row["startTimeLocal"] = "private-invalid-date"
            if offset == 0:
                return [row, row] if malformed == "duplicate" else [row]
            return []

    settings = Settings()
    with pytest.raises(StridelogError):
        synchronize(settings, MalformedSource().open, today=date(2025, 1, 2))
    engine = database_engine(settings.data_dir)
    try:
        with Session(engine) as session:
            assert session.get(SyncCursor, "activities") is None
            assert list(session.scalars(select(SyncRun.status))) == ["failed"]
    finally:
        engine.dispose()


def test_cli_sync_uses_source_factory_without_exposing_private_details(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = FakeSource()

    def factory(_settings: Settings) -> AbstractContextManager[FakeSource]:
        return source.open()

    monkeypatch.setattr("stridelog.cli.open_personal_source", factory)
    result = CliRunner().invoke(app, ["sync", "--since", date.today().isoformat()])
    assert result.exit_code == 0, result.output
    assert "Updated raw documents:" in result.output
    assert "Original ZIPs downloaded: 0" in result.output
    assert str(Settings().data_dir) not in result.output


def test_taxonomy_descendants_and_explicit_running_keys_are_selected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class HierarchicalSource(FakeSource):
        def activity_types(self) -> JsonValue:
            return [
                {"key": "running"},
                {"key": "trail_running", "parent": "running"},
                {"key": "mountain_run", "parent": {"key": "trail_running"}},
                {"key": "cycling"},
            ]

    monkeypatch.setenv("STRIDELOG_RUNNING_ACTIVITY_TYPES", '["running","owner_run"]')
    source = HierarchicalSource()
    source.rows = [
        activity(1, 1, "mountain_run"),
        activity(2, 1, "owner_run"),
        activity(3, 1, "cycling"),
    ]
    synchronize(Settings(), source.open, today=date(2025, 1, 1))
    assert source.original_calls == ["1", "2"]


def test_ctrl_c_records_interruption_and_releases_lock_for_resume() -> None:
    class InterruptedSource(FakeSource):
        def wellness(self, dataset: str, day: date) -> JsonValue:
            raise KeyboardInterrupt

    settings = Settings()
    with pytest.raises(KeyboardInterrupt):
        synchronize(settings, InterruptedSource().open, today=date(2025, 1, 2))
    synchronize(settings, FakeSource().open, today=date(2025, 1, 2))
    engine = database_engine(settings.data_dir)
    try:
        with Session(engine) as session:
            assert list(session.scalars(select(SyncRun.error_code))) == ["interrupted", None]
    finally:
        engine.dispose()
