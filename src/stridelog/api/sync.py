"""Explicit sync trigger and in-memory progress polling."""

from collections.abc import Callable
from concurrent.futures import Future
from datetime import date
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from stridelog.analysis import analyze
from stridelog.api.dependencies import get_session
from stridelog.api.schemas import SyncRequest, SyncStarted, SyncStatus
from stridelog.config import Settings
from stridelog.errors import StridelogError
from stridelog.garmin import open_personal_source
from stridelog.ingest.sync import synchronize
from stridelog.rebuild import rebuild

router = APIRouter(prefix="/api/v1")
SessionDependency = Annotated[Session, Depends(get_session)]
SyncRunner = Callable[[Settings, date | None], None]


def run_sync_pipeline(settings: Settings, since: date | None) -> None:
    """Run the same explicit archive, rebuild and analysis steps as the CLI."""
    synchronize(settings, lambda: open_personal_source(settings), since=since)
    report = rebuild(settings)
    if report.failed_activities or report.failed_documents:
        raise StridelogError("Sync completed with local rebuild failures.")
    analyze(settings)


@router.post("/sync", response_model=SyncStarted, status_code=status.HTTP_202_ACCEPTED)
def start_sync(
    payload: SyncRequest,
    request: Request,
    _session: SessionDependency,
) -> SyncStarted:
    if payload.since is not None and payload.since > date.today():
        raise HTTPException(status_code=422, detail="since must not be in the future.")

    with request.app.state.sync_lock:
        current: Future[None] | None = request.app.state.sync_future
        if current is not None and not current.done():
            raise HTTPException(status_code=409, detail="A sync is already running.")
        job_id = uuid4().hex
        runner = request.app.state.sync_runner
        future = request.app.state.executor.submit(
            runner, request.app.state.settings, payload.since
        )
        request.app.state.sync_job_id = job_id
        request.app.state.sync_future = future
    return SyncStarted(job_id=job_id, status="running")


@router.get("/sync/{job_id}", response_model=SyncStatus)
def sync_status(job_id: str, request: Request, _session: SessionDependency) -> SyncStatus:
    with request.app.state.sync_lock:
        current_id: str | None = request.app.state.sync_job_id
        future: Future[None] | None = request.app.state.sync_future
        if job_id != current_id or future is None:
            raise HTTPException(status_code=404, detail="Sync job not found.")
        if not future.done():
            return SyncStatus(job_id=job_id, status="running", message="Sync in progress.")
        try:
            future.result()
        except StridelogError, SQLAlchemyError, OSError:
            return SyncStatus(
                job_id=job_id,
                status="failed",
                message="Sync failed; inspect local diagnostics.",
            )
        return SyncStatus(job_id=job_id, status="succeeded", message="Sync completed.")


__all__ = ["router", "run_sync_pipeline"]
