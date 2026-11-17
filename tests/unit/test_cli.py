"""Smoke tests for the installed command-line interface."""

from importlib.metadata import version

from typer.testing import CliRunner

from stridelog.cli import app

runner = CliRunner()


def test_version() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert result.stdout.strip() == f"stridelog {version('stridelog')}"


def test_no_arguments_shows_help_without_claiming_features_exist() -> None:
    result = runner.invoke(app, [], color=False)
    assert result.exit_code == 2
    assert "--version" in result.stdout


def test_unimplemented_command_is_rejected() -> None:
    result = runner.invoke(app, ["sync"])
    assert result.exit_code == 2
