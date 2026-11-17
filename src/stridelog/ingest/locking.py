"""A process-owned lock: release automatically on exit, including a killed sync."""

import errno
import sys
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

if sys.platform == "win32":
    import msvcrt
else:
    import fcntl

from stridelog.errors import StridelogError


@contextmanager
def sync_lock(data_dir: Path) -> Generator[None]:
    """Keep the lock inode in place so competing processes cannot bypass it."""
    data_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    target = data_dir / "sync.lock"
    if target.is_symlink() or target.resolve().parent != data_dir.resolve():
        raise StridelogError("Linked sync lock rejected.")
    with target.open("a+b") as handle:
        if target.stat().st_size == 0:
            handle.write(b"\0")
            handle.flush()
        handle.seek(0)
        try:
            if sys.platform == "win32":
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            if error.errno in {errno.EACCES, errno.EAGAIN, errno.EDEADLK}:
                raise StridelogError(
                    "Another sync/rebuild holds the lock; retry after it finishes."
                ) from None
            raise
        try:
            yield
        finally:
            if sys.platform == "win32":
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
