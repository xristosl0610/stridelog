"""Smoke tests for the installed command-line interface."""

import re
from importlib.metadata import version

import pytest
from typer.testing import CliRunner

from stridelog.cli import app

runner = CliRunner()


def test_version() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert result.stdout.strip() == f"stridelog {version('stridelog')}"


@pytest.mark.parametrize("force_color", [None, "1"])
def test_no_arguments_shows_help_without_claiming_features_exist(force_color: str | None) -> None:
    result = runner.invoke(app, [], color=False, env={"FORCE_COLOR": force_color})
    assert result.exit_code == 2
    plain_help = re.sub(r"\x1b\[[0-9;]*m", "", result.stdout)
    assert "--version" in plain_help


def test_unimplemented_command_is_rejected() -> None:
    result = runner.invoke(app, ["sync"])
    assert result.exit_code == 2
