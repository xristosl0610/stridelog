"""Owner-run, bounded Personal API discovery; never run against real data in tests."""

import argparse
import base64
import json
import logging
import math
import os
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from time import monotonic, sleep
from typing import cast
from urllib.parse import urlsplit
from uuid import uuid4

from garmin_personal_api.auth import PersonalApiAuthenticator
from garmin_personal_api.client import GarminPersonalApiClient
from garmin_personal_api.constants import DEFAULT_BASE_URL, TOKEN_PATH
from garmin_personal_api.errors import GarminPersonalApiError, HttpError
from requests import PreparedRequest, Response, Session

ROOT = Path(__file__).resolve().parents[1]
ORIGIN = "https://personal.connectapi.garmin.com"
SEARCH_PATH = "/activitylist-service/activities/search/activities"
PROJECTION = "Allowlisted fields, first array items and a depth limit of four."
SAFE_FIELDS = frozenset(
    {
        "data",
        "activityId",
        "activityType",
        "eventType",
        "activityTypeDTO",
        "eventTypeDTO",
        "summaryDTO",
        "metadataDTO",
        "timeZoneUnitDTO",
        "typeId",
        "parentTypeId",
        "typeKey",
        "key",
        "parent",
        "lastUpdateDate",
        "uploadedDate",
        "timeZone",
        "distance",
        "duration",
        "elapsedDuration",
        "movingDuration",
        "averageHR",
        "maxHR",
        "averageSpeed",
        "elevationGain",
        "elevationLoss",
        "elevationCorrected",
        "averageRunCadence",
        "averageRunningCadenceInStepsPerMinute",
        "strideLength",
        "avgStrideLength",
        "startTimeGMT",
        "startTimeLocal",
        "beginTimestamp",
        "heartRate",
        "restingValue",
        "minValue",
        "maxValue",
        "bodyBattery",
        "chargedValue",
        "drainedValue",
        "latestValue",
        "stress",
        "avgLevel",
        "movement",
        "steps",
        "sleepTimeSeconds",
        "deepSleepSeconds",
        "lightSleepSeconds",
        "remSleepSeconds",
        "awakeSleepSeconds",
        "sleepScore",
        "hrvSummary",
        "weeklyAvg",
        "lastNightAvg",
        "status",
        "zones",
        "heartRateZones",
        "trainingMethod",
        "restingHeartRateUsed",
        "lactateThresholdHeartRateUsed",
        "maxHeartRateUsed",
        "restingHrAutoUpdateUsed",
        "zone1Floor",
        "zone2Floor",
        "zone3Floor",
        "zone4Floor",
        "zone5Floor",
        "sport",
        "sportType",
        "sportTypeId",
        "maxHeartRate",
        "restingHeartRate",
        "zoneNumber",
        "low",
        "high",
        "lowerBound",
        "upperBound",
        "calendarDate",
        "date",
        "value",
        "vo2Max",
        "generic",
        "cycling",
        "rowing",
        "vo2MaxValue",
        "vo2MaxPreciseValue",
    }
)


class DiscoveryError(Exception):
    """A fixed, safe-to-display discovery failure; never include private values."""


@dataclass(frozen=True)
class Probe:
    """One named GET; only its public name is displayed before confirmation."""

    name: str
    path: str
    params: Mapping[str, str | int] | None = None


def build_plan(day: date, race_id: str) -> tuple[Probe, ...]:
    """Build the fixed ten-GET plan without performing I/O."""
    single_day = {"startDate": day.isoformat(), "endDate": day.isoformat()}
    return (
        Probe("activity_types", "/activity-service/activity/activityTypes/simple"),
        Probe("search_first", SEARCH_PATH, {"start": 0, "limit": 20}),
        Probe("search_second", SEARCH_PATH, {"start": 20, "limit": 20}),
        Probe(
            "history_sample",
            SEARCH_PATH,
            {
                "start": 0,
                "limit": 1,
                "startDate": "2025-01-01",
                "endDate": "2025-01-31",
            },
        ),
        Probe("race_details", f"/activity-service/activity/{race_id}"),
        Probe("daily_summary", "/usersummary-service/v2/dailysummaries", single_day),
        Probe("sleep", "/sleep-service/sleep/dailySleepSummariesByDate", single_day),
        Probe("hrv", f"/hrv-service/hrv/daily/{day.isoformat()}/{day.isoformat()}"),
        Probe("zones", "/biometric-service/heartRateZones/v2"),
        Probe(
            "vo2_max", f"/metrics-service/metrics/maxmet/daily/{day.isoformat()}/{day.isoformat()}"
        ),
    )


class DiscoverySession(Session):
    """Enforce origin, request budget, spacing and no redirects at the transport."""

    def __init__(self, plan: Sequence[Probe]) -> None:
        super().__init__()
        self._paths = {probe.path for probe in plan}
        self._gets = 0
        self._posts = 0
        self._last_started: float | None = None
        self.retry_after_present = False

    def send(self, request: PreparedRequest, **kwargs: object) -> Response:
        """Send only approved requests; the default adapter performs no retries."""
        address = urlsplit(request.url or "")
        if f"{address.scheme}://{address.netloc}" != ORIGIN:
            raise DiscoveryError("Unexpected request origin; request blocked.")
        if request.method == "GET" and address.path in self._paths and self._gets < 10:
            self._gets += 1
        elif request.method == "POST" and address.path == TOKEN_PATH and self._posts < 1:
            self._posts += 1
        else:
            raise DiscoveryError("Request is outside the approved plan or budget; blocked.")
        if self._last_started is not None:
            remaining = 1.0 - (monotonic() - self._last_started)
            if remaining > 0:
                sleep(remaining)
        self._last_started = monotonic()
        kwargs["allow_redirects"] = False
        response = super().send(request, **kwargs)
        self.retry_after_present = "Retry-After" in response.headers
        if 300 <= response.status_code < 400:
            response.close()
            raise DiscoveryError("Redirect rejected; no further requests sent.")
        return response


def _mapping(value: object) -> Mapping[object, object] | None:
    if isinstance(value, Mapping):
        return cast(Mapping[object, object], value)
    return None


def _array(value: object) -> Sequence[object] | None:
    if isinstance(value, list):
        return cast(list[object], value)
    return None


def shape(value: object, depth: int = 0) -> dict[str, object]:
    """Project only fixed field names and JSON kinds, never scalar values."""
    mapping = _mapping(value)
    array = _array(value)
    if mapping is not None:
        result: dict[str, object] = {"kind": "object"}
        if depth < 4:
            result["fields"] = {
                name: shape(mapping[name], depth + 1)
                for name in sorted(SAFE_FIELDS)
                if name in mapping
            }
            result["other_fields_omitted"] = any(key not in SAFE_FIELDS for key in mapping)
        return result
    if array is not None:
        result = {"kind": "array", "has_items": bool(array)}
        if array and depth < 4:
            result["first_item"] = shape(array[0], depth + 1)
        return result
    if value is None:
        return {"kind": "null"}
    if isinstance(value, bool):
        return {"kind": "boolean"}
    if isinstance(value, (int, float)):
        return {"kind": "number"}
    if isinstance(value, str):
        return {"kind": "string"}
    raise DiscoveryError("Unexpected non-JSON response type; inspection stopped.")


def _page_ids(value: object) -> set[str] | None:
    mapping = _mapping(value)
    rows = _array(mapping.get("data") if mapping is not None else value)
    if not rows:
        return None
    identifiers: set[str] = set()
    for row in rows:
        item = _mapping(row)
        identifier = item.get("activityId") if item is not None else None
        if isinstance(identifier, bool) or not isinstance(identifier, (str, int)):
            return None
        identifiers.add(str(identifier))
    return identifiers


def _race_facts(value: object) -> dict[str, object]:
    details = _mapping(value)
    event = _mapping(details.get("eventTypeDTO")) if details is not None else None
    metadata = _mapping(details.get("metadataDTO")) if details is not None else None
    key = event.get("typeKey") if event is not None else None
    marker = metadata.get("lastUpdateDate") if metadata is not None else None
    marker_format = shape(marker)["kind"]
    if isinstance(marker, str):
        try:
            datetime.fromisoformat(marker)
        except ValueError:
            marker_format = "other_string"
        else:
            marker_format = "iso_datetime" if "T" in marker or " " in marker else "iso_date"
    return {
        "event_key_is_race": key == "race" if isinstance(key, str) else "unavailable",
        "last_update_format": marker_format,
        "edit_behavior": "not_tested",
    }


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        number = float(value)
    except OverflowError:
        return None
    return number if math.isfinite(number) else None


def _token_facts(token: str) -> dict[str, object]:
    try:
        encoded = token.split(".")[1]
        claims = _mapping(json.loads(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))))
    except (IndexError, ValueError, UnicodeError) as error:
        raise DiscoveryError("Token timing could not be inspected safely.") from error
    if claims is None:
        raise DiscoveryError("Token timing claims are not a JSON object.")
    issued, expires = _number(claims.get("iat")), _number(claims.get("exp"))
    if expires is None:
        raise DiscoveryError("Token expiry is not a finite numeric claim; inspection stopped.")
    lifetime = "unavailable"
    if issued is not None:
        hours = (expires - issued) / 3600
        lifetime = (
            "under_one_hour"
            if 0 < hours < 1
            else (
                "one_to_48_hours"
                if 1 <= hours <= 48
                else "over_48_hours"
                if hours > 48
                else "invalid"
            )
        )
    return {
        "exp_present": "exp" in claims,
        "iat_present": "iat" in claims,
        "lifetime_band": lifetime,
    }


def _private_directory(text: str) -> Path:
    selected = text.strip().strip('"')
    if not selected:
        raise DiscoveryError("A protected directory must be selected.")
    folder = Path(selected).expanduser().resolve(strict=True)
    if not folder.is_dir() or folder.is_relative_to(ROOT.resolve()):
        raise DiscoveryError("Choose an existing protected directory outside the repository.")
    return folder


def _private_folder(text: str) -> Path:
    folder = _private_directory(text)
    cache = folder / "bearer-token.json"
    if not cache.resolve().is_relative_to(folder):
        raise DiscoveryError("Bearer cache must remain in the selected private directory.")
    if cache.exists():
        cached = _mapping(json.loads(cache.read_text(encoding="utf-8")))
        if cached is None or any(
            not isinstance(cached.get(key), str) or not cached.get(key)
            for key in ("access_token", "fingerprint")
        ):
            raise DiscoveryError("Existing bearer cache is invalid; inspect it privately.")
        expiry = cached.get("expires_at")
        if _number(expiry) is None:
            raise DiscoveryError("Existing bearer cache expiry is invalid; inspect it privately.")
    return folder


def inspect_saved(text: str) -> dict[str, object]:
    """Project three fixed saved responses without credentials, writes or HTTP."""
    folder = _private_directory(text)
    observations: dict[str, object] = {}
    for name in ("activity_types", "vo2_max", "zones"):
        source = folder / f"{name}.json"
        if source.is_symlink() or source.resolve().parent != folder:
            raise DiscoveryError("Linked response file rejected; inspection stopped.")
        if not source.is_file():
            raise DiscoveryError(f"Required saved response {name}.json is missing.")
        payload: object = json.loads(source.read_text(encoding="utf-8"))
        observations[name] = {"shape": shape(payload)}
    return {
        "mode": "offline_saved_responses",
        "projection": PROJECTION,
        "probes": observations,
        "limits": "Saved JSON only; HTTP status, freshness, units and full schema are unverified.",
    }


def _execute(
    client: GarminPersonalApiClient,
    session: DiscoverySession,
    plan: Sequence[Probe],
    output: Path,
) -> tuple[dict[str, object], dict[str, dict[str, object]], bool]:
    payloads: dict[str, object] = {}
    observations: dict[str, dict[str, object]] = {}
    for probe in plan:
        try:
            payload: object = client.get(probe.path, params=probe.params)
        except HttpError as error:
            observations[probe.name] = {
                "status": "http_error",
                "http_status": error.status_code,
                "retry_after_present": session.retry_after_present,
            }
            if error.status_code in (401, 403, 429):
                return payloads, observations, False
        else:
            with (output / f"{probe.name}.json").open("x", encoding="utf-8") as file:
                json.dump(payload, file)
            observations[probe.name] = {"status": "ok", "shape": shape(payload)}
            payloads[probe.name] = payload
    return payloads, observations, True


def run(folder: Path, day: date, race_id: str, api_key: str) -> dict[str, object]:
    """Run the confirmed batch, keeping JSON responses in the protected folder."""
    for name in (
        "garmin_personal_api",
        "garmin_personal_api.auth",
        "garmin_personal_api.client",
        "garmin_personal_api._credentials",
    ):
        logging.getLogger(name).disabled = True
    plan = build_plan(day, race_id)
    output = folder / f"api-check-{uuid4().hex}"
    output.mkdir()
    with DiscoverySession(plan) as session:
        auth = PersonalApiAuthenticator(
            session=session, bearer_token_cache_file=folder / "bearer-token.json"
        )
        token = auth.obtain_token(api_key)
        token_facts = _token_facts(token.access_token)
        client = GarminPersonalApiClient(token.access_token, session=session)
        payloads, observations, completed = _execute(client, session, plan, output)
    first, second = (
        _page_ids(payloads.get("search_first")),
        _page_ids(payloads.get("search_second")),
    )
    return {
        "completed": completed,
        "has_http_errors": any(item["status"] == "http_error" for item in observations.values()),
        "token_timing_unverified_claims": token_facts,
        "projection": PROJECTION,
        "probes": observations,
        "page_id_relation": "unavailable"
        if first is None or second is None
        else ("overlap" if first & second else "disjoint"),
        "race": _race_facts(payloads.get("race_details")),
        "limits": "Page/range maxima, complete history and edit behavior are not established.",
    }


def _print_report(report: Mapping[str, object]) -> None:
    print("Shareable structural report (copy only this JSON, not the entered inputs):")
    print(json.dumps(report, indent=2, sort_keys=True))


def main(argv: Sequence[str] | None = None) -> int:
    """Prompt for private inputs and display only the final structural report."""
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument(
        "--live", action="store_true", help="Prompt to confirm the fixed ten-GET batch."
    )
    modes.add_argument(
        "--offline", action="store_true", help="Inspect three saved JSON responses without HTTP."
    )
    args = parser.parse_args(argv)
    if not args.live and not args.offline:
        print("No requests sent. Use --offline for saved JSON or --live to confirm discovery.")
        return 0
    try:
        if args.offline:
            report = inspect_saved(input("Existing protected api-check-* response directory: "))
            _print_report(report)
            return 0
        if (
            DEFAULT_BASE_URL != ORIGIN
            or os.environ.get("GARMIN_PERSONAL_API_BASE_URL", ORIGIN).rstrip("/") != ORIGIN
        ):
            raise DiscoveryError("Unexpected API origin override; no requests sent.")
        key = os.environ.get("GARMIN_PERSONAL_API_KEY", "").strip()
        if not key:
            raise DiscoveryError(
                "Missing API key. Launch with uv --env-file .env; never paste the key."
            )
        folder = _private_folder(input("Existing protected discovery directory: "))
        selected_day = input("Private sample day (YYYY-MM-DD): ").strip()
        day = date.fromisoformat(selected_day)
        if day.isoformat() != selected_day:
            raise DiscoveryError("Use the exact YYYY-MM-DD date format.")
        race_id = input("Private known-race activity ID: ").strip()
        if not race_id.isascii() or not race_id.isdecimal() or int(race_id) <= 0:
            raise DiscoveryError("The private activity ID must be a positive ASCII integer.")
        print(
            "Up to 10 paced GETs, plus one token exchange only if needed. No retries or redirects."
        )
        print("Requests:", ", ".join(probe.name for probe in build_plan(day, race_id)))
        if input("Type RUN to send this batch: ").strip() != "RUN":
            print("Cancelled; no requests sent.")
            return 0
        report = run(folder, day, race_id, key)
        _print_report(report)
        print(
            "JSON responses are in a new api-check-* subfolder of your selected private directory."
        )
        if not report["completed"] or report["has_http_errors"]:
            print(
                "Some requests failed or the batch stopped; see sanitized statuses above.",
                file=sys.stderr,
            )
            return 1
        return 0
    except DiscoveryError as error:
        print(f"Discovery stopped: {error}", file=sys.stderr)
    except HttpError as error:
        print(
            f"Authentication failed with HTTP {error.status_code}; batch stopped.", file=sys.stderr
        )
    except (GarminPersonalApiError, OSError, ValueError) as error:
        print(
            f"Discovery failed ({type(error).__name__}); private details were not printed.",
            file=sys.stderr,
        )
    except EOFError, KeyboardInterrupt:
        print("Input cancelled; no further requests sent.", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
