"""Command-line entry point; feature commands arrive in later phases."""

from importlib.metadata import version
from typing import Annotated

import typer

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
        return
    typer.echo(ctx.get_help())
    raise typer.Exit(code=2)
