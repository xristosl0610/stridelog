"""Real official client, mocked HTTP only; test pacing, auth and privacy."""

import base64
import json
import logging
import time
from datetime import date
from io import BytesIO
from pathlib import Path
from typing import Never

import pytest
from garmin_personal_api.auth import PersonalApiAuthenticator
from requests import PreparedRequest, Response, Session
from requests.adapters import HTTPAdapter
from requests.exceptions import ConnectionError as NetworkError
from urllib3 import HTTPResponse

from stridelog.config import Settings
from stridelog.errors import StridelogError
from stridelog.garmin import ORIGIN, PacedSession, open_personal_source

pytestmark = pytest.mark.usefixtures("private_environment")


class Clock:
    """Monotonic fake time; no validation test actually waits for retries."""

    def __init__(self) -> None:
        self.now = 0.0
        self.waits: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, delay: float) -> None:
        assert delay >= 0
        self.waits.append(delay)
        self.now += delay


def response(request: PreparedRequest, status: int, content: bytes) -> Response:
    return HTTPAdapter().build_response(
        request, HTTPResponse(body=BytesIO(content), status=status, preload_content=False)
    )


def test_each_attempt_is_paced_with_backoff_and_retry_after(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = Clock()
    starts: list[float] = []
    statuses = iter([429, 503, 200, 200])

    def send(_session: Session, request: PreparedRequest, **kwargs: object) -> Response:
        assert kwargs["allow_redirects"] is False
        starts.append(clock.now)
        result = response(request, next(statuses), b"[]")
        if result.status_code == 429:
            result.headers["Retry-After"] = "3"
        return result

    monkeypatch.setattr("stridelog.garmin.monotonic", clock.monotonic)
    monkeypatch.setattr("stridelog.garmin.sleep", clock.sleep)
    monkeypatch.setattr(Session, "send", send)
    with PacedSession(1) as session:
        assert session.get(f"{ORIGIN}/synthetic").status_code == 200
        assert session.get(f"{ORIGIN}/synthetic").status_code == 200
    assert starts == [0, 3, 5, 6]


@pytest.mark.parametrize("failure", ["network", "server", "other_5xx", "redirect", "retry_header"])
def test_failures_are_bounded_and_do_not_leak_request_details(
    failure: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = Clock()
    attempts: list[str] = []

    def send(_session: Session, request: PreparedRequest, **_kwargs: object) -> Response:
        attempts.append("attempt")
        if failure == "network":
            raise NetworkError("private-upstream-body")
        status = {"server": 500, "other_5xx": 501, "redirect": 302, "retry_header": 429}[failure]
        result = response(request, status, b"private-upstream-body")
        if failure == "retry_header":
            result.headers["Retry-After"] = "invalid-private-header"
        return result

    monkeypatch.setattr("stridelog.garmin.monotonic", clock.monotonic)
    monkeypatch.setattr("stridelog.garmin.sleep", clock.sleep)
    monkeypatch.setattr(Session, "send", send)
    with PacedSession(1) as session, pytest.raises(StridelogError) as caught:
        session.get(f"{ORIGIN}/private-activity?private-date=synthetic")
    assert len(attempts) == (5 if failure in {"network", "server", "other_5xx"} else 1)
    assert "private" not in str(caught.value)
    assert ORIGIN not in str(caught.value)


def test_origin_and_method_rejected_before_network() -> None:
    with PacedSession(1) as session:
        with pytest.raises(StridelogError, match="origin"):
            session.get("https://example.invalid/synthetic")
        with pytest.raises(StridelogError, match="method"):
            session.delete(f"{ORIGIN}/synthetic")
        with pytest.raises(StridelogError, match="method"):
            session.post(f"{ORIGIN}/synthetic")


def test_real_client_refreshes_once_reuses_cache_and_suppresses_private_logs(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    clock = Clock()
    methods: list[str | None] = []
    query_statuses = iter([401, 200, 200, 200, 200, 200, 200, 200])

    def send(_session: Session, request: PreparedRequest, **_kwargs: object) -> Response:
        methods.append(request.method)
        if request.method == "POST":
            claims = (
                base64.urlsafe_b64encode(json.dumps({"exp": time.time() + 7200}).encode())
                .decode()
                .rstrip("=")
            )
            return response(request, 200, f"synthetic.{claims}.synthetic".encode())
        status = next(query_statuses)
        return response(request, status, b"private-upstream-body" if status == 401 else b"[]")

    monkeypatch.setattr("stridelog.garmin.monotonic", clock.monotonic)
    monkeypatch.setattr("stridelog.garmin.sleep", clock.sleep)
    monkeypatch.setattr(Session, "send", send)
    settings = Settings()
    caplog.set_level(logging.DEBUG)
    with open_personal_source(settings) as source:
        assert source.activity_types() == []
        assert source.activities(date(2025, 1, 1), date(2025, 1, 2), 0) == []
        assert source.details("1") == []
        assert source.wellness("daily", date(2025, 1, 1)) == []
        assert source.wellness("sleep", date(2025, 1, 1)) == []
        assert source.wellness("hrv", date(2025, 1, 1)) == []
        assert source.original("1") == b"[]"
    assert methods.count("POST") == 2
    assert "private-upstream-body" not in caplog.text
    assert "synthetic-key-not-a-credential" not in caplog.text
    assert "startDate" not in caplog.text
    with open_personal_source(settings):
        pass
    assert methods.count("POST") == 2


@pytest.mark.parametrize("status", [401, 403, 404])
def test_sdk_errors_are_sanitized_and_401_is_refreshed_only_once(
    status: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    posts: list[int] = []

    def send(_session: Session, request: PreparedRequest, **_kwargs: object) -> Response:
        if request.method == "POST":
            posts.append(1)
            claims = (
                base64.urlsafe_b64encode(json.dumps({"exp": time.time() + 7200}).encode())
                .decode()
                .rstrip("=")
            )
            return response(request, 200, f"synthetic.{claims}.synthetic".encode())
        return response(request, status, b"private-upstream-body")

    monkeypatch.setattr(Session, "send", send)
    clock = Clock()
    monkeypatch.setattr("stridelog.garmin.sleep", clock.sleep)
    monkeypatch.setattr("stridelog.garmin.monotonic", clock.monotonic)
    with open_personal_source(Settings()) as source, pytest.raises(StridelogError) as caught:
        source.details("1")
    assert "private-upstream-body" not in str(caught.value)
    assert len(posts) == (2 if status == 401 else 1)


def test_invalid_cache_and_base_url_fail_before_authentication(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings()
    settings.data_dir.mkdir()
    cache = settings.data_dir / "bearer-token.json"
    cache.write_text("{private-invalid-cache", encoding="utf-8")
    with (
        pytest.raises(StridelogError, match="Invalid bearer cache"),
        open_personal_source(settings),
    ):
        pass
    monkeypatch.setenv("GARMIN_PERSONAL_API_BASE_URL", "https://example.invalid")
    with pytest.raises(StridelogError, match="base URL"), open_personal_source(settings):
        pass
    assert not logging.getLogger("garmin_personal_api.client").disabled


def test_missing_or_empty_key_file_is_reported_without_private_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("GARMIN_PERSONAL_API_KEY")
    settings = Settings()
    with pytest.raises(StridelogError, match="missing"), open_personal_source(settings):
        pass
    key_file = Path.home() / ".config" / "garmin" / "connect-personal-api-key"
    key_file.parent.mkdir(parents=True)
    key_file.write_text("", encoding="utf-8")
    with pytest.raises(StridelogError, match="empty"), open_personal_source(settings):
        pass


@pytest.mark.parametrize("failure", ["authentication", "json"])
def test_authentication_and_malformed_json_errors_do_not_expose_raw_bodies(
    failure: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    def send(_session: Session, request: PreparedRequest, **_kwargs: object) -> Response:
        if request.method == "POST" and failure != "authentication":
            claims = (
                base64.urlsafe_b64encode(json.dumps({"exp": time.time() + 7200}).encode())
                .decode()
                .rstrip("=")
            )
            return response(request, 200, f"synthetic.{claims}.synthetic".encode())
        return response(request, 403 if failure == "authentication" else 200, b"private-raw-body")

    monkeypatch.setattr(Session, "send", send)
    with pytest.raises(StridelogError) as caught, open_personal_source(Settings()) as source:
        source.details("1")
    assert "private-raw-body" not in str(caught.value)


def test_interrupted_sdk_cache_write_preserves_last_complete_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings()
    settings.data_dir.mkdir()
    cache = settings.data_dir / "bearer-token.json"
    previous = b'{"fingerprint":"synthetic","access_token":"synthetic","expires_at":1}'
    cache.write_bytes(previous)
    cache.chmod(0o600)

    def interrupted(
        auth: PersonalApiAuthenticator, _key: str, *, force_refresh: bool = False
    ) -> Never:
        auth.bearer_token_cache_file.write_bytes(b"{partial")
        raise KeyboardInterrupt

    monkeypatch.setattr(PersonalApiAuthenticator, "obtain_token", interrupted)
    with pytest.raises(KeyboardInterrupt), open_personal_source(settings):
        pass
    assert cache.read_bytes() == previous
    assert not list(settings.data_dir.glob(".tmp-*"))
