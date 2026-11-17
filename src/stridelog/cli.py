"""Thin command-line boundary; configuration and storage values stay private."""

from datetime import date
from importlib.metadata import version
from typing import Annotated

import typer
from alembic.util.exc import CommandError as MigrationError
from pydantic import ValidationError
from pydantic_settings import SettingsError
from sqlalchemy.exc import SQLAlchemyError

from stridelog.config import Settings
from stridelog.db.engine import database_status
from stridelog.diagnostics import doctor_report
from stridelog.errors import StridelogError
from stridelog.garmin import open_personal_source
from stridelog.ingest.sync import synchronize
from stridelog.rebuild import quality_report
from stridelog.rebuild import rebuild as rebuild_archive

app = typer.Typer(add_completion=False, pretty_exceptions_enable=False)


@app.callback(invoke_without_command=True)
def cli(
    ctx: typer.Context,
    show_version: Annotated[
        bool, typer.Option("--version", help="Show the installed version and exit.", is_eager=True)
    ] = False,
) -> None:
    """Local-first running analytics for Garmin data."""
    if show_version:
        typer.echo(f"stridelog {version('stridelog')}")
        raise typer.Exit()
    if ctx.invoked_subcommand is not None:
        return
    typer.echo(ctx.get_help())
    raise typer.Exit(code=2)


def _settings() -> Settings:
    try:
        return Settings()
    except ValidationError as error:
        fields = sorted({str(item["loc"][0]) for item in error.errors(include_input=False)})
        raise StridelogError(f"Invalid configuration fields: {', '.join(fields)}.") from None
    except SettingsError, UnicodeError:
        raise StridelogError("Invalid configuration format; check the ignored .env.") from None


def _failure(error: Exception) -> None:
    message = (
        str(error)
        if isinstance(error, StridelogError)
        else f"Local storage operation failed ({type(error).__name__}); details withheld."
    )
    typer.echo(message, err=True)
    raise typer.Exit(code=1)


@app.command()
def doctor(
    initialize: Annotated[
        bool, typer.Option("--initialize", help="Create storage and apply migrations; no network.")
    ] = False,
) -> None:
    """Check settings, key presence, expiry and local storage without network."""
    try:
        report = doctor_report(_settings(), initialize=initialize)
    except (StridelogError, SQLAlchemyError, MigrationError, OSError) as error:
        _failure(error)
    else:
        for line in report.lines:
            typer.echo(line)
        if not report.ready:
            raise typer.Exit(code=1)


@app.command()
def status() -> None:
    """Show aggregate operational status, never activity values or identifiers."""
    try:
        snapshot = database_status(_settings().data_dir)
        if snapshot is None:
            raise StridelogError("Database is not initialized; run doctor --initialize.")
    except (StridelogError, SQLAlchemyError, MigrationError, OSError) as error:
        _failure(error)
    else:
        typer.echo(f"Archived files: {snapshot.raw_files}")
        typer.echo(f"Sync runs: {snapshot.sync_runs}")
        typer.echo(f"Last sync: {snapshot.last_run_status or 'never'}")


@app.command()
def sync(
    since: Annotated[
        str | None, typer.Option(help="Reconcile history since an inclusive YYYY-MM-DD.")
    ] = None,
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Describe scope without network or storage writes.")
    ] = False,
) -> None:
    """Archive running activities and daily wellness, resuming durable progress."""
    try:
        settings = _settings()
        selected: date | None = None
        if since is not None:
            try:
                selected = date.fromisoformat(since)
                if selected.isoformat() != since or selected > date.today():
                    raise ValueError
            except ValueError:
                raise StridelogError("--since must be YYYY-MM-DD and not in the future.") from None
        if dry_run:
            typer.echo("Plan: running activities, daily summaries, sleep, HRV and current zones.")
            typer.echo(
                "History: explicit --since reconciliation."
                if selected is not None
                else "History: saved progress and lookbacks, or the initial archive baseline."
            )
            typer.echo("No network or storage writes; existing cursors are not opened.")
            return
        typer.echo("Sync started; requests are paced. Press Ctrl+C to pause safely.")
        report = synchronize(settings, lambda: open_personal_source(settings), since=selected)
    except (StridelogError, SQLAlchemyError, MigrationError, OSError) as error:
        _failure(error)
    else:
        typer.echo(f"Updated raw documents: {report.updated_documents}")
        typer.echo(f"Original ZIPs downloaded: {report.downloaded_originals}")


@app.command()
def rebuild() -> None:
    """Rebuild typed measurements offline; preserve raw files and user annotations."""
    try:
        report = rebuild_archive(_settings())
    except (StridelogError, SQLAlchemyError, MigrationError, OSError) as error:
        _failure(error)
    else:
        typer.echo(f"Activities imported: {report.imported_activities}")
        typer.echo(f"Activities reported as failed: {report.failed_activities}")
        typer.echo(f"Documents reported as failed: {report.failed_documents}")
        typer.echo(f"Rebuild seconds: {report.elapsed_s:.2f}")
        comparison = (
            "not available"
            if report.matches_previous is None
            else "yes"
            if report.matches_previous
            else "no"
        )
        typer.echo(f"Matches previous rebuild: {comparison}")
        typer.echo("Private findings saved under the data directory's reports folder.")
        if report.failed_activities or report.failed_documents:
            raise typer.Exit(code=1)


@app.command("dq-report")
def dq_report() -> None:
    """Refresh the private quality report from the last rebuild's stored findings."""
    try:
        count = quality_report(_settings())
    except (StridelogError, SQLAlchemyError, MigrationError, OSError) as error:
        _failure(error)
    else:
        typer.echo(f"Quality findings: {count}")
        typer.echo("Private report saved under the data directory's reports folder.")
