"""Atomic private-file replacement, shared by archival and credential caching."""

import os
from pathlib import Path
from tempfile import NamedTemporaryFile

from stridelog.errors import StridelogError


def write_atomic(target: Path, payload: bytes, *, immutable: bool = False) -> None:
    """Replace under the caller's single-writer lock after path validation."""
    if target.exists():
        if target.read_bytes() == payload:
            return
        if immutable:
            raise StridelogError("Immutable archive content differs; existing file preserved.")
    target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with NamedTemporaryFile(dir=target.parent, prefix=".tmp-", delete=False) as handle:
        temporary = Path(handle.name)
        try:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        except OSError, KeyboardInterrupt:
            handle.close()
            temporary.unlink(missing_ok=True)
            raise
    try:
        os.replace(temporary, target)
        if os.name == "posix":
            directory = os.open(target.parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
    finally:
        temporary.unlink(missing_ok=True)
