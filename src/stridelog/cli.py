"""Thin command-line boundary; configuration and storage values stay private."""

from importlib.metadata import version
from typing import Annotated

import typer
from alembic.util.exc import CommandError as MigrationError
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

from stridelog.config import Settings
from stridelog.db.engine import database_status
from stridelog.diagnostics import doctor_report
from stridelog.errors import StridelogError

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
