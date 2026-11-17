"""Atomic current JSON, immutable content versions and checksum bookkeeping."""

import hashlib
import json
from io import BytesIO
from pathlib import Path, PurePosixPath
from zipfile import BadZipFile, ZipFile

from pydantic import JsonValue
from sqlalchemy.orm import Session

from stridelog.db.models import RawFile
from stridelog.errors import StridelogError
from stridelog.storage import write_atomic


class RawStore:
    """Write files first; the caller commits manifest/progress together afterwards."""

    def __init__(self, root: Path, session: Session, run_id: str) -> None:
        self.root = root.resolve()
        self.session = session
        self.run_id = run_id

    def _target(self, relative: str) -> Path:
        path = PurePosixPath(relative)
        if (
            path.is_absolute()
            or not path.parts
            or ".." in path.parts
            or "\\" in relative
            or ":" in relative
        ):
            raise StridelogError("Invalid archive path.")
        target = self.root.joinpath(*path.parts)
        if target.is_symlink() or not target.resolve().is_relative_to(self.root):
            raise StridelogError("Linked archive target rejected.")
        return target

    def _record(self, relative: str, payload: bytes, dataset: str, source_id: str) -> bool:
        checksum = hashlib.sha256(payload).hexdigest()
        existing = self.session.get(RawFile, relative)
        if existing is not None and existing.sha256 == checksum:
            return False
        self.session.merge(
            RawFile(
                relative_path=relative,
                dataset=dataset,
                source_id=source_id,
                sha256=checksum,
                size_bytes=len(payload),
                run_id=self.run_id,
            )
        )
        return True

    def _write(self, relative: str, payload: bytes, *, immutable: bool) -> None:
        write_atomic(self._target(relative), payload, immutable=immutable)

    def has(self, relative: str) -> bool:
        """Check manifest/file agreement instead of trusting mere path presence."""
        target = self._target(relative)
        manifest = self.session.get(RawFile, relative)
        if manifest is None or not target.is_file():
            return False
        if hashlib.sha256(target.read_bytes()).hexdigest() != manifest.sha256:
            raise StridelogError("Archive checksum mismatch; repair local storage before syncing.")
        return True

    def write_json(self, relative: str, payload: JsonValue, dataset: str, source_id: str) -> bool:
        """Preserve each unique payload before atomically updating its current copy."""
        try:
            serialized = json.dumps(
                payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
            ).encode()
        except ValueError, TypeError:
            raise StridelogError("Unsupported raw JSON; archive was not updated.") from None
        checksum = hashlib.sha256(serialized).hexdigest()
        target = self._target(relative)
        manifest = self.session.get(RawFile, relative)
        if manifest is not None and target.is_file():
            current_checksum = hashlib.sha256(target.read_bytes()).hexdigest()
            if current_checksum != manifest.sha256:
                previous = self._target(f"{relative}.versions/{current_checksum}.json")
                if (
                    not previous.is_file()
                    or hashlib.sha256(previous.read_bytes()).hexdigest() != current_checksum
                ):
                    raise StridelogError(
                        "Archive checksum mismatch; current JSON was not replaced."
                    )
        version = f"{relative}.versions/{checksum}.json"
        self._write(version, serialized, immutable=True)
        self._record(version, serialized, dataset, source_id)
        self._write(relative, serialized, immutable=False)
        return self._record(relative, serialized, dataset, source_id)

    @staticmethod
    def _validate_original(payload: bytes) -> None:
        try:
            with ZipFile(BytesIO(payload)) as archive:
                if not any(name.lower().endswith(".fit") for name in archive.namelist()):
                    raise StridelogError("Original ZIP has no FIT member; nothing archived.")
        except BadZipFile:
            raise StridelogError(
                "Original download is not a valid ZIP; nothing archived."
            ) from None

    def has_original(self, relative: str, activity_id: str) -> bool:
        """Adopt a durable original after an interrupted manifest transaction."""
        target = self._target(relative)
        if not target.is_file():
            return False
        payload = target.read_bytes()
        self._validate_original(payload)
        if self.session.get(RawFile, relative) is not None:
            self.has(relative)
        self._record(relative, payload, "originals", activity_id)
        return True

    def write_original(self, relative: str, payload: bytes, activity_id: str) -> None:
        """Never replace an existing ZIP, even when Garmin returns different bytes."""
        self._validate_original(payload)
        self._write(relative, payload, immutable=True)
        self._record(relative, payload, "originals", activity_id)
