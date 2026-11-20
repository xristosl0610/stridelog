"""FastAPI dependencies for local database access."""

from collections.abc import Generator

from fastapi import Request
from sqlalchemy.orm import Session

from stridelog.db.engine import DATABASE_NAME
from stridelog.errors import StridelogError


def get_session(request: Request) -> Generator[Session]:
    """Provide one session per request without creating or migrating storage."""
    settings = request.app.state.settings
    if not (settings.data_dir / DATABASE_NAME).is_file():
        raise StridelogError("Local database is not initialized; run doctor --initialize.")
    with Session(request.app.state.engine) as session:
        yield session
