"""Official-client boundary with paced retries and sanitized transport errors."""

import logging
import math
import os
from collections.abc import Callable, Generator, Mapping
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from tempfile import NamedTemporaryFile
from time import monotonic, sleep
from typing import Protocol
from urllib.parse import urlsplit

from garmin_personal_api.auth import PersonalApiAuthenticator
from garmin_personal_api.client import GarminPersonalApiClient
from garmin_personal_api.errors import GarminPersonalApiError, HttpError
from pydantic import JsonValue, TypeAdapter, ValidationError
from requests import PreparedRequest, Response, Session
from requests.exceptions import ConnectionError as NetworkError
from requests.exceptions import RequestException, Timeout
from urllib3 import HTTPResponse
from urllib3.exceptions import InvalidHeader, MaxRetryError
from urllib3.util.retry import Retry

from stridelog.config import Settings
from stridelog.errors import StridelogError
from stridelog.storage import write_atomic

ORIGIN = "https://personal.connectapi.garmin.com"
AUTH_PATH = "/personalapitoken-service/personal-api/personal-api-key/token"
JSON = TypeAdapter(JsonValue)


class GarminSource(Protocol):
    """Raw-data provider; fake implementations must never contact Garmin."""

    def activity_types(self) -> JsonValue: ...
    def activities(self, start: date, end: date, offset: int) -> JsonValue: ...
    def details(self, activity_id: str) -> JsonValue: ...
    def original(self, activity_id: str) -> bytes: ...
    def wellness(self, dataset: str, day: date) -> JsonValue: ...
    def zones(self) -> JsonValue: ...


class PacedSession(Session):
    """Pace every HTTP attempt, including token exchanges and retries."""

    def __init__(self, interval: float) -> None:
        super().__init__()
        self.interval = interval
        self._last_started: float | None = None

    def send(self, request: PreparedRequest, **kwargs: object) -> Response:
        """Use bounded urllib3 retry accounting without hidden adapter retries."""
        address = urlsplit(request.url or "")
        if f"{address.scheme}://{address.netloc}" != ORIGIN:
            raise StridelogError("Unexpected Garmin origin; request blocked.")
        if request.method not in {"GET", "POST"} or (
            request.method == "POST" and address.path != AUTH_PATH
        ):
            raise StridelogError("Unexpected Garmin method; request blocked.")
        policy = Retry(
            total=4,
            backoff_factor=1,
            allowed_methods=frozenset({"GET", "POST"}),
            status_forcelist=(429, *range(500, 600)),
            respect_retry_after_header=True,
        )
        kwargs["allow_redirects"] = False
        while True:
            if self._last_started is not None:
                delay = self.interval - (monotonic() - self._last_started)
                if delay > 0:
                    sleep(delay)
            self._last_started = monotonic()
            try:
                response = super().send(request, **kwargs)
            except NetworkError, Timeout:
                try:
                    policy = policy.increment(method=request.method)
                except MaxRetryError:
                    raise StridelogError(
                        "Garmin network retries exhausted; retry sync later."
                    ) from None
                sleep(policy.get_backoff_time())
                continue
            if 300 <= response.status_code < 400:
                response.close()
                raise StridelogError("Garmin redirect rejected.")
            if not policy.is_retry(request.method, response.status_code):
                return response
            retry_response = HTTPResponse(status=response.status_code, headers=response.headers)
            response.close()
            try:
                policy = policy.increment(method=request.method, response=retry_response)
                delay = policy.get_retry_after(retry_response) or policy.get_backoff_time()
            except MaxRetryError, InvalidHeader:
                raise StridelogError("Garmin retries exhausted or retry header invalid.") from None
            sleep(delay)


class CachedAuthenticator:
    """Keep the upstream client's non-atomic cache writes away from the durable cache."""

    def __init__(self, session: Session, cache: Path, staging: Path) -> None:
        self.upstream = PersonalApiAuthenticator(session=session, bearer_token_cache_file=staging)
        self.cache = cache
        self.staging = staging

    def access_token(self, key: str, *, refresh: bool = False) -> str:
        """Publish only a complete SDK cache, including after a forced refresh."""
        token = self.upstream.obtain_token(key, force_refresh=refresh)
        write_atomic(self.cache, self.staging.read_bytes())
        return token.access_token


@contextmanager
def _atomic_authenticator(session: Session, cache: Path) -> Generator[CachedAuthenticator]:
    cache.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with NamedTemporaryFile(dir=cache.parent, prefix=".tmp-bearer-", delete=False) as handle:
        staging = Path(handle.name)
    try:
        if cache.is_file():
            write_atomic(staging, cache.read_bytes())
        else:
            staging.unlink()
        yield CachedAuthenticator(session, cache, staging)
    finally:
        staging.unlink(missing_ok=True)


def _token(auth: CachedAuthenticator, key: str, *, refresh: bool = False) -> str:
    try:
        return auth.access_token(key, refresh=refresh)
    except GarminPersonalApiError, RequestException:
        raise StridelogError(
            "Garmin authentication failed; check the key and its expiration in Garmin Connect."
        ) from None


class PersonalApiSource:
    """Translate the sync interface into official, uninterpreted API operations."""

    def __init__(
        self, client: GarminPersonalApiClient, auth: CachedAuthenticator, key: str
    ) -> None:
        self.client = client
        self.auth = auth
        self._key = key

    def _call[T](self, operation: Callable[[], T]) -> T:
        try:
            try:
                return operation()
            except HttpError as error:
                if error.status_code != 401:
                    raise
                self.client.update_bearer_token(_token(self.auth, self._key, refresh=True))
                return operation()
        except HttpError as error:
            if error.status_code in {401, 403}:
                raise StridelogError(
                    "Garmin access denied; check the key in Garmin Connect."
                ) from None
            raise StridelogError(f"Garmin request failed (HTTP {error.status_code}).") from None
        except GarminPersonalApiError, RequestException, ValueError:
            raise StridelogError(
                "Garmin returned an invalid response or the connection failed."
            ) from None

    def _get(
        self, path: str, params: Mapping[str, str | int | float | bool] | None = None
    ) -> JsonValue:
        payload: object = self._call(lambda: self.client.get(path, params=params))
        try:
            return JSON.validate_python(payload, strict=True)
        except ValidationError:
            raise StridelogError("Garmin returned unsupported JSON data.") from None

    def activity_types(self) -> JsonValue:
        """Fetch public taxonomy keys before selecting running activities."""
        return self._get("/activity-service/activity/activityTypes/simple")

    def activities(self, start: date, end: date, offset: int) -> JsonValue:
        """Fetch a bounded page using activity-local date filters."""
        return self._get(
            "/activitylist-service/activities/search/activities",
            {
                "start": offset,
                "limit": 20,
                "startDate": start.isoformat(),
                "endDate": end.isoformat(),
            },
        )

    def details(self, activity_id: str) -> JsonValue:
        """Preserve details without interpreting the update marker."""
        return self._get(f"/activity-service/activity/{activity_id}")

    def original(self, activity_id: str) -> bytes:
        """Download the original ZIP without extracting or interpreting FIT."""
        return self._call(lambda: self.client.download_activity(activity_id))

    def wellness(self, dataset: str, day: date) -> JsonValue:
        """Use equal start/end dates; null HRV remains valid raw JSON."""
        span = {"startDate": day.isoformat(), "endDate": day.isoformat()}
        if dataset == "daily":
            return self._get("/usersummary-service/v2/dailysummaries", span)
        if dataset == "sleep":
            return self._get("/sleep-service/sleep/dailySleepSummariesByDate", span)
        if dataset == "hrv":
            return self._get(f"/hrv-service/hrv/daily/{day.isoformat()}/{day.isoformat()}")
        raise StridelogError("Unknown wellness dataset.")

    def zones(self) -> JsonValue:
        """Archive the current profile, without claiming zone history."""
        return self._get("/biometric-service/heartRateZones/v2")


def _configured_key(settings: Settings) -> str:
    key = settings.garmin_personal_api_key
    if key is not None:
        return key.get_secret_value().strip()
    key_file = Path.home() / ".config" / "garmin" / "connect-personal-api-key"
    try:
        plain_key = key_file.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        raise StridelogError("Garmin API key is missing; configure the ignored .env.") from None
    except UnicodeError:
        raise StridelogError("Garmin API key file is not valid UTF-8.") from None
    if not plain_key:
        raise StridelogError("Garmin API key is empty.")
    if os.name == "posix" and key_file.stat().st_mode & 0o077:
        raise StridelogError(
            "API key file permissions are too broad; restrict locally to owner-only."
        )
    return plain_key


def _cache_file(settings: Settings) -> Path:
    cache = settings.data_dir / "bearer-token.json"
    if cache.is_symlink() or cache.resolve().parent != settings.data_dir.resolve():
        raise StridelogError("Linked bearer cache rejected.")
    if cache.exists():
        try:
            cached = TypeAdapter(dict[str, JsonValue]).validate_json(cache.read_bytes())
            fingerprint, token = cached.get("fingerprint"), cached.get("access_token")
            expiration = cached.get("expires_at")
            if (
                not isinstance(fingerprint, str)
                or not fingerprint
                or not isinstance(token, str)
                or not token.strip()
                or isinstance(expiration, bool)
                or not isinstance(expiration, int | float)
                or not math.isfinite(expiration)
            ):
                raise ValueError
        except ValidationError, ValueError, OverflowError:
            raise StridelogError(
                "Invalid bearer cache; remove it locally before retrying."
            ) from None
        if os.name == "posix" and cache.stat().st_mode & 0o077:
            raise StridelogError(
                "Bearer cache permissions are too broad; restrict locally to owner-only."
            )
    return cache


@contextmanager
def open_personal_source(settings: Settings) -> Generator[PersonalApiSource]:
    """Own one session and suppress upstream path/body logging for its lifetime."""
    if os.environ.get("GARMIN_PERSONAL_API_BASE_URL", ORIGIN).rstrip("/") != ORIGIN:
        raise StridelogError("Garmin base URL override rejected.")
    names = (
        "garmin_personal_api.auth",
        "garmin_personal_api.client",
        "garmin_personal_api._credentials",
        "urllib3.connectionpool",
    )
    loggers = [(logging.getLogger(name), logging.getLogger(name).disabled) for name in names]
    for logger, _disabled in loggers:
        logger.disabled = True
    try:
        plain_key, cache = _configured_key(settings), _cache_file(settings)
        with (
            PacedSession(settings.request_interval_s) as session,
            _atomic_authenticator(session, cache) as auth,
        ):
            client = GarminPersonalApiClient(_token(auth, plain_key), session=session)
            yield PersonalApiSource(client, auth, plain_key)
    finally:
        for logger, disabled in loggers:
            logger.disabled = disabled
