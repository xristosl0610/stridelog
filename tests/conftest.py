"""Opt-in synthetic settings isolation, shared by local service acceptance tests."""

import os
from pathlib import Path

import pytest


@pytest.fixture
def private_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Prevent settings tests from reading owner credentials or opening sockets."""

    def synthetic_checkout(_directory: Path) -> Path:
        return tmp_path / "checkout"

    def forbid_network(*_args: object, **_kwargs: object) -> None:
        pytest.fail("Tests must not access the network")

    for key in os.environ:
        if key.startswith(("STRIDELOG_", "GARMIN_PERSONAL_API_")):
            monkeypatch.delenv(key)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    monkeypatch.setattr("stridelog.config.REPOSITORY_ROOT", tmp_path / "checkout")
    monkeypatch.setattr("stridelog.config.find_checkout_root", synthetic_checkout)
    monkeypatch.setattr("socket.socket.connect", forbid_network)
    monkeypatch.setenv("STRIDELOG_DATA_DIR", str(tmp_path / "private"))
    monkeypatch.setenv("GARMIN_PERSONAL_API_KEY", "synthetic-key-not-a-credential")
