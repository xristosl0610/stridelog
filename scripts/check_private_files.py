"""Reject private data paths even when files are force-added to Git."""

import sys
from pathlib import PurePosixPath

DATA_SUFFIXES = frozenset({".fit", ".zip", ".sqlite", ".sqlite3", ".db", ".gpx", ".tcx"})
PRIVATE_DIRECTORIES = frozenset({"raw", "data", "exports", ".stridelog"})
PRIVATE_NAMES = frozenset({"connect-personal-api-key", "connect-personal-api-token"})


def is_private_path(filename: str) -> bool:
    """Return whether a repository-relative path can contain private data."""
    path = PurePosixPath(filename.replace("\\", "/").lower())
    return (
        path.suffix in DATA_SUFFIXES
        or path.name.endswith(
            (".sqlite-wal", ".sqlite-shm", ".sqlite3-wal", ".sqlite3-shm", ".db-wal", ".db-shm")
        )
        or path.name in PRIVATE_NAMES
        or (path.name.startswith(".env") and path.name != ".env.example")
        or bool(PRIVATE_DIRECTORIES.intersection(path.parts[:-1]))
    )


def main(filenames: list[str]) -> int:
    """Report forbidden staged paths and return a nonzero exit code."""
    rejected = [filename for filename in filenames if is_private_path(filename)]
    for filename in rejected:
        print(f"Private data must not be committed: {filename}", file=sys.stderr)
    return int(bool(rejected))


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
