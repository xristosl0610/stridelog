"""Local-only notebook reads without loading credential-bearing settings."""

import os
from collections.abc import Sequence
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import DeclarativeBase, Session
from sqlalchemy.sql.elements import ColumnElement

from stridelog.db.engine import DATABASE_NAME, database_engine


def _data_dir() -> Path:
    configured = os.environ.get("STRIDELOG_DATA_DIR")
    data_dir = (
        Path(configured).expanduser().resolve()
        if configured is not None
        else Path.home() / ".stridelog"
    )
    repository = next(
        (parent for parent in Path(__file__).resolve().parents if (parent / ".git").exists()),
        None,
    )
    if repository is not None and data_dir.is_relative_to(repository):
        raise ValueError("Notebook data must stay outside the repository.")
    return data_dir


def read_table(
    model: type[DeclarativeBase],
    columns: Sequence[str],
    predicate: ColumnElement[bool] | None = None,
) -> list[dict[str, object]]:
    """Read selected typed columns from the local database without loading secrets."""
    data_dir = _data_dir()
    if not (data_dir / DATABASE_NAME).is_file():
        raise FileNotFoundError(
            "Local database not found. Sync or rebuild first, or set STRIDELOG_DATA_DIR."
        )
    statement = select(*(getattr(model, column) for column in columns))
    if predicate is not None:
        statement = statement.where(predicate)
    engine = database_engine(data_dir)
    try:
        with Session(engine) as session:
            return [dict(row) for row in session.execute(statement).mappings()]
    finally:
        engine.dispose()
