"""Thin command-line boundary; configuration and storage values stay private."""

import webbrowser
from datetime import date
from importlib.metadata import version
from typing import Annotated, Literal

import typer
import uvicorn
from alembic.util.exc import CommandError as MigrationError
from pydantic import ValidationError
from pydantic_settings import SettingsError
from sqlalchemy.exc import SQLAlchemyError

from stridelog.activity_annotations import set_race_details, set_steady_run
from stridelog.analysis import analyze as run_analysis
from stridelog.api.app import create_app
from stridelog.athlete import save_profile
from stridelog.config import Settings
from stridelog.db.engine import database_status
from stridelog.diagnostics import doctor_report
from stridelog.errors import StridelogError
from stridelog.garmin import open_personal_source
from stridelog.ingest.sync import synchronize
from stridelog.rebuild import quality_report
from stridelog.rebuild import rebuild as rebuild_archive

app = typer.Typer(add_completion=False, pretty_exceptions_enable=False)
profile_app = typer.Typer(add_completion=False, pretty_exceptions_enable=False)
activity_app = typer.Typer(add_completion=False, pretty_exceptions_enable=False)
app.add_typer(profile_app, name="profile")
app.add_typer(activity_app, name="activity")


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
        rebuild_report = rebuild_archive(settings)
        if rebuild_report.failed_activities or rebuild_report.failed_documents:
            raise StridelogError(
                "Sync completed but local rebuild reported failures; inspect reports locally."
            )
        analysis_report = run_analysis(settings)
    except (StridelogError, SQLAlchemyError, MigrationError, OSError) as error:
        _failure(error)
    else:
        typer.echo(f"Updated raw documents: {report.updated_documents}")
        typer.echo(f"Original ZIPs downloaded: {report.downloaded_originals}")
        typer.echo(
            "Activities analyzed: "
            f"{analysis_report.calculated_activities} calculated, "
            f"{analysis_report.skipped_activities} unchanged."
        )
        typer.echo(f"Daily analytics rows: {analysis_report.calculated_days}")


@app.command()
def analyze() -> None:
    """Recalculate changed activity metrics and refresh daily analytics offline."""
    try:
        report = run_analysis(_settings())
    except (StridelogError, SQLAlchemyError, MigrationError, OSError) as error:
        _failure(error)
    else:
        typer.echo(
            "Activities analyzed: "
            f"{report.calculated_activities} calculated, {report.skipped_activities} unchanged."
        )
        typer.echo(f"Daily analytics rows: {report.calculated_days}")


@activity_app.command("steady-run")
def annotate_steady_run(
    activity_id: Annotated[int, typer.Argument(min=1)],
    is_steady_run: Annotated[
        bool, typer.Option("--steady/--not-steady", help="Mark whether the run was steady.")
    ] = True,
) -> None:
    """Set or clear the manual steady-run annotation used for decoupling."""
    try:
        settings = _settings()
        set_steady_run(settings, activity_id, is_steady_run)
        report = run_analysis(settings)
    except (StridelogError, SQLAlchemyError, MigrationError, OSError) as error:
        _failure(error)
    else:
        typer.echo(
            "Steady-run annotation saved; analytics refreshed "
            f"({report.calculated_activities} activities recalculated)."
        )


@activity_app.command("race")
def annotate_race(
    activity_id: Annotated[int, typer.Argument(min=1)],
    is_race_override: Annotated[
        bool | None, typer.Option("--race/--not-race", help="Override the Garmin race flag.")
    ] = None,
    race_name: Annotated[str | None, typer.Option(help="Optional local race name.")] = None,
    official_time_s: Annotated[
        float | None, typer.Option(help="Optional official result time in seconds.")
    ] = None,
    use_garmin: Annotated[
        bool, typer.Option("--from-garmin", help="Clear local race overrides and details.")
    ] = False,
) -> None:
    """Set a local race override or result without printing personal values."""
    try:
        settings = _settings()
        set_race_details(
            settings,
            activity_id,
            is_race_override=is_race_override,
            race_name=race_name,
            official_time_s=official_time_s,
            use_garmin=use_garmin,
        )
        report = run_analysis(settings)
    except (StridelogError, SQLAlchemyError, MigrationError, OSError) as error:
        _failure(error)
    else:
        typer.echo(
            "Race annotation saved; analytics refreshed "
            f"({report.calculated_activities} activities recalculated)."
        )


@profile_app.command("set")
def set_profile(
    effective_from: str,
    max_hr_bpm: Annotated[float, typer.Option(help="Dated maximum heart rate in bpm.")],
    resting_hr_bpm: Annotated[float, typer.Option(help="Dated resting heart rate in bpm.")],
    sex_for_trimp: Annotated[
        Literal["female", "other"],
        typer.Option(help="TRIMP constant selection; choose the applicable formula."),
    ],
    threshold_hr_bpm: Annotated[
        float | None, typer.Option(help="Optional lactate-threshold heart rate in bpm.")
    ] = None,
    zone_floors: Annotated[
        str | None,
        typer.Option(help="Optional five comma-separated zone floors in bpm."),
    ] = None,
) -> None:
    """Save a dated athlete profile without printing its personal values."""
    try:
        try:
            day = date.fromisoformat(effective_from)
        except ValueError:
            raise StridelogError("--effective-from must be YYYY-MM-DD.") from None
        if day.isoformat() != effective_from:
            raise StridelogError("--effective-from must be YYYY-MM-DD.")
        try:
            floors = (
                None
                if zone_floors is None
                else tuple(float(value.strip()) for value in zone_floors.split(","))
            )
        except ValueError:
            raise StridelogError("--zone-floors must be five comma-separated numbers.") from None
        settings = _settings()
        save_profile(
            settings,
            day,
            max_hr_bpm=max_hr_bpm,
            resting_hr_bpm=resting_hr_bpm,
            threshold_hr_bpm=threshold_hr_bpm,
            sex_for_trimp=sex_for_trimp,
            hr_zone_floors_bpm=floors,
        )
        report = run_analysis(settings)
    except (StridelogError, SQLAlchemyError, MigrationError, OSError) as error:
        _failure(error)
    else:
        typer.echo(
            "Athlete profile saved; analytics refreshed "
            f"({report.calculated_activities} activities recalculated)."
        )


@profile_app.command("setup")
def setup_profile() -> None:
    """Interactively save a dated profile without echoing personal values."""
    typer.echo(
        "Enter the date these values became valid, not the date they were observed. "
        "Inputs are hidden; leave optional fields blank."
    )
    effective_from = typer.prompt("Effective date (YYYY-MM-DD)", hide_input=True)
    maximum = typer.prompt("Maximum heart rate (bpm)", hide_input=True)
    resting = typer.prompt("Resting heart rate (bpm)", hide_input=True)
    selection = (
        typer.prompt(
            "TRIMP constants (female or other; see metrics documentation)", hide_input=True
        )
        .strip()
        .lower()
    )
    threshold = typer.prompt(
        "Optional threshold heart rate (bpm)", default="", show_default=False, hide_input=True
    )
    zones = typer.prompt(
        "Optional five zone floors (comma-separated bpm)",
        default="",
        show_default=False,
        hide_input=True,
    )
    try:
        max_hr_bpm = float(maximum)
        resting_hr_bpm = float(resting)
        threshold_hr_bpm = float(threshold) if threshold.strip() else None
    except ValueError:
        _failure(StridelogError("Heart-rate values must be numbers."))
        return
    if selection not in ("female", "other"):
        _failure(StridelogError("TRIMP constants must be female or other."))
        return
    set_profile(
        effective_from,
        max_hr_bpm,
        resting_hr_bpm,
        selection,
        threshold_hr_bpm,
        zones if zones.strip() else None,
    )


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


@app.command()
def serve() -> None:
    """Start the loopback-only API and open its Swagger documentation."""
    try:
        settings = _settings()
        snapshot = database_status(settings.data_dir)
        if snapshot is None:
            raise StridelogError("Database is not initialized; run doctor --initialize.")
        webbrowser.open("http://127.0.0.1:8000/docs")
        uvicorn.run(
            create_app(settings),
            host="127.0.0.1",
            port=8000,
            access_log=False,
        )
    except (StridelogError, SQLAlchemyError, MigrationError, OSError) as error:
        _failure(error)
