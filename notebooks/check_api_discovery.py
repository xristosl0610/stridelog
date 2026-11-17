"""Offline synthetic checks for the optional, owner-run API discovery helper."""

import base64
import contextlib
import io
import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

import api_discovery as discovery
from requests import PreparedRequest, Response, Session


def _token() -> str:
    claims = json.dumps({"iat": 4102358400, "exp": 4102444800}).encode()
    encoded = base64.urlsafe_b64encode(claims).decode().rstrip("=")
    return f"synthetic.{encoded}.not-a-real-signature"


class SyntheticResponse(Response):
    """Populate requests' protected body fields within a response subclass."""

    def set_body(self, content: bytes) -> None:
        self._content = content
        self._content_consumed = True


class ApiDiscoveryChecks(unittest.TestCase):
    """Use the real pinned client with a mocked HTTP transport; never Garmin."""

    def setUp(self) -> None:
        root = Path(__file__).resolve().parents[1]
        (root / ".tools").mkdir(exist_ok=True)
        scratch = TemporaryDirectory(prefix="api-check-test-", dir=root / ".tools")
        self.addCleanup(scratch.cleanup)
        directory = Path(scratch.name)
        self.repository = directory / "repository"
        self.repository.mkdir()
        self.private = directory / "private"
        self.private.mkdir()
        self.now = 0.0
        self.calls: list[tuple[str, str, float]] = []
        self.failure_status: int | None = None
        self.auth_status = 200
        self.malformed_response = False
        self.failure_path = "/activity-service/activity/activityTypes/simple"
        self.stdout = io.StringIO()
        self.stderr = io.StringIO()
        self.enterContext(patch.object(discovery, "ROOT", self.repository))
        self.enterContext(patch.object(discovery, "monotonic", side_effect=lambda: self.now))
        self.enterContext(patch.object(discovery, "sleep", side_effect=self._sleep))
        self.enterContext(
            patch.dict(
                os.environ,
                {
                    "GARMIN_PERSONAL_API_KEY": "synthetic-key",
                    "GARMIN_PERSONAL_API_BASE_URL": discovery.ORIGIN,
                },
            )
        )
        self.send = self.enterContext(
            patch.object(Session, "send", autospec=True, side_effect=self._respond)
        )

    def _sleep(self, seconds: float) -> None:
        self.now += seconds

    def _respond(self, session: Session, request: PreparedRequest, **kwargs: object) -> Response:
        self.assertIs(kwargs["allow_redirects"], False)
        address = urlsplit(request.url or "")
        self.calls.append((request.method or "", address.path, self.now))
        response = SyntheticResponse()
        response.status_code = 200
        response.encoding = "utf-8"
        response.request = request
        if request.method == "POST":
            response.status_code = self.auth_status
            response.set_body(_token().encode())
            return response
        if address.path == self.failure_path and self.failure_status is not None:
            response.status_code = self.failure_status
            response.headers["Retry-After"] = "10"
            response.headers["Location"] = "https://example.invalid/private"
            payload: object = {"message": "private-response-body", "key": "synthetic-key"}
        elif address.path == discovery.SEARCH_PATH:
            start = parse_qs(address.query).get("start", ["0"])[0]
            payload = [
                {
                    "activityId": 123456789 if start == "0" else 987654321,
                    "activityType": {"typeKey": "running"},
                    "averageHR": 197,
                    "startTimeLocal": "2030-01-02T03:04:05",
                    "private-dynamic-field": "private-response-body",
                }
            ]
        elif address.path.endswith("/123456789"):
            payload = {
                "eventTypeDTO": {"typeKey": "race"},
                "metadataDTO": {"lastUpdateDate": "2030-01-02T03:04:05Z"},
                "activityName": "private-response-body",
            }
        elif address.path.startswith("/hrv-service/"):
            payload = None
        elif address.path in {
            "/activity-service/activity/activityTypes/simple",
            "/usersummary-service/v2/dailysummaries",
            "/sleep-service/sleep/dailySleepSummariesByDate",
            "/biometric-service/heartRateZones/v2",
            "/metrics-service/metrics/maxmet/daily/2030-01-02/2030-01-02",
        }:
            payload = {
                "data": [
                    {
                        "value": 67.12345,
                        "calendarDate": "2030-01-02",
                        "private-response-body": "private-response-body",
                    }
                ],
                "maxHeartRate": 197,
                "restingHeartRate": 53,
            }
        else:
            self.fail("Unexpected synthetic GET target")
        response.set_body(
            b"private-response-body" if self.malformed_response else json.dumps(payload).encode()
        )
        return response

    def _main(self, answers: list[str] | None = None, argv: list[str] | None = None) -> int:
        if answers is None:
            answers = [str(self.private), "2030-01-02", "123456789", "RUN"]
        with (
            patch("builtins.input", side_effect=answers),
            contextlib.redirect_stdout(self.stdout),
            contextlib.redirect_stderr(self.stderr),
        ):
            return discovery.main(["--live"] if argv is None else argv)

    def _report(self) -> dict[str, object]:
        marker = "Shareable structural report (copy only this JSON, not the entered inputs):\n"
        text = self.stdout.getvalue().split(marker, 1)[1]
        value: dict[str, object] = json.JSONDecoder().raw_decode(text)[0]
        return value

    def _assert_private_output(self) -> None:
        output = self.stdout.getvalue() + self.stderr.getvalue()
        for secret in (
            str(self.private),
            "synthetic-key",
            _token(),
            "2030-01-02",
            "123456789",
            "987654321",
            "private-response-body",
            "private-dynamic-field",
            "67.12345",
            "197",
        ):
            with self.subTest(secret=secret):
                self.assertNotIn(secret, output)

    def test_confirmed_batch_is_bounded_paced_private_and_structural(self) -> None:
        self.assertEqual(self._main(), 0)
        self.assertEqual([method for method, _, _ in self.calls].count("POST"), 1)
        self.assertEqual([method for method, _, _ in self.calls].count("GET"), 10)
        for left, right in zip(self.calls, self.calls[1:], strict=False):
            self.assertGreaterEqual(right[2] - left[2], 1.0)
        report = self._report()
        self.assertIs(report["completed"], True)
        self.assertIs(report["has_http_errors"], False)
        self.assertEqual(report["page_id_relation"], "disjoint")
        self.assertEqual(
            report["race"],
            {
                "event_key_is_race": True,
                "last_update_format": "iso_datetime",
                "edit_behavior": "not_tested",
            },
        )
        directories = list(self.private.glob("api-check-*"))
        self.assertEqual(len(directories), 1)
        self.assertEqual(len(list(directories[0].glob("*.json"))), 10)
        raw = json.loads((directories[0] / "race_details.json").read_text("utf-8"))
        self.assertEqual(raw["activityName"], "private-response-body")
        self.assertIn('"kind": "null"', self.stdout.getvalue())
        self._assert_private_output()

    def test_cached_batch_does_not_exchange_again_or_overwrite_responses(self) -> None:
        self.assertEqual(self._main(), 0)
        self.calls.clear()
        self.assertEqual(self._main(), 0)
        self.assertEqual(len(self.calls), 10)
        self.assertTrue(all(method == "GET" for method, _, _ in self.calls))
        directories = list(self.private.glob("api-check-*"))
        self.assertEqual(len(directories), 2)
        for directory in directories:
            self.assertEqual(len(list(directory.glob("*.json"))), 10)
        self._assert_private_output()

    def test_dry_run_and_cancel_send_nothing(self) -> None:
        self.assertEqual(self._main(argv=[]), 0)
        self.assertEqual(self._main([str(self.private), "2030-01-02", "123456789", "CANCEL"]), 0)
        self.send.assert_not_called()
        self.assertEqual(list(self.private.iterdir()), [])
        self._assert_private_output()

    def _saved_responses(self) -> None:
        payloads = {
            "activity_types": [{"key": "private-response-body", "parent": None}],
            "vo2_max": [
                {
                    "generic": {
                        "calendarDate": "2030-01-02",
                        "vo2MaxValue": 67.12345,
                        "vo2MaxPreciseValue": 67.12345,
                    },
                    "cycling": None,
                    "rowing": None,
                    "private-dynamic-field": "private-response-body",
                }
            ],
            "zones": [
                {
                    "sport": "private-response-body",
                    "trainingMethod": "private-response-body",
                    "restingHeartRateUsed": 197,
                    "lactateThresholdHeartRateUsed": 197,
                    "maxHeartRateUsed": 197,
                    "restingHrAutoUpdateUsed": True,
                    **{f"zone{number}Floor": 197 for number in range(1, 6)},
                }
            ],
        }
        for name, payload in payloads.items():
            (self.private / f"{name}.json").write_text(json.dumps(payload), "utf-8")
        for name in (".env", "bearer-token.json"):
            (self.private / name).write_text("private-response-body", "utf-8")

    def test_offline_review_reads_only_fixed_response_files_without_authentication(self) -> None:
        self._saved_responses()
        original_files = {path.name: path.read_bytes() for path in self.private.iterdir()}
        original_read = Path.read_text
        expected = {
            self.private / f"{name}.json" for name in ("activity_types", "vo2_max", "zones")
        }
        seen: set[Path] = set()

        def read_response(path: Path, *, encoding: str) -> str:
            self.assertIn(path, expected)
            seen.add(path)
            return original_read(path, encoding=encoding)

        with (
            patch.dict(
                os.environ,
                {
                    "GARMIN_PERSONAL_API_KEY": "",
                    "GARMIN_PERSONAL_API_BASE_URL": "https://example.invalid",
                },
            ),
            patch.object(Path, "read_text", autospec=True, side_effect=read_response),
            patch.object(discovery.PersonalApiAuthenticator, "obtain_token") as authenticate,
        ):
            self.assertEqual(self._main([str(self.private)], argv=["--offline"]), 0)
        authenticate.assert_not_called()
        self.send.assert_not_called()
        self.assertEqual(seen, expected)
        report = self._report()
        self.assertEqual(report["mode"], "offline_saved_responses")
        self.assertNotIn("token_timing_unverified_claims", report)
        for field in (
            "key",
            "generic",
            "cycling",
            "rowing",
            "vo2MaxValue",
            "vo2MaxPreciseValue",
            "trainingMethod",
            "restingHeartRateUsed",
            "lactateThresholdHeartRateUsed",
            "maxHeartRateUsed",
            "restingHrAutoUpdateUsed",
            *(f"zone{number}Floor" for number in range(1, 6)),
        ):
            self.assertIn(f'"{field}":', self.stdout.getvalue())
        self.assertEqual(
            {path.name for path in self.private.iterdir()},
            {"activity_types.json", "vo2_max.json", "zones.json", ".env", "bearer-token.json"},
        )
        self.assertEqual(
            {path.name: path.read_bytes() for path in self.private.iterdir()}, original_files
        )
        self._assert_private_output()

    def test_documented_vo2_wrapper_projects_kinds_not_measurements(self) -> None:
        self.assertEqual(
            discovery.shape([{"generic": {"vo2MaxValue": 67.12345}}]),
            {
                "kind": "array",
                "has_items": True,
                "first_item": {
                    "kind": "object",
                    "other_fields_omitted": False,
                    "fields": {
                        "generic": {
                            "kind": "object",
                            "other_fields_omitted": False,
                            "fields": {"vo2MaxValue": {"kind": "number"}},
                        }
                    },
                },
            },
        )

    def test_offline_missing_or_malformed_file_never_prints_a_partial_report(self) -> None:
        self._saved_responses()
        source = self.private / "zones.json"
        source.unlink()
        self.assertEqual(self._main([str(self.private)], argv=["--offline"]), 2)
        source.write_text("private-response-body", "utf-8")
        self.assertEqual(self._main([str(self.private)], argv=["--offline"]), 2)
        self.assertNotIn("Shareable structural report", self.stdout.getvalue())
        self.send.assert_not_called()
        self._assert_private_output()

    def test_offline_rejects_repository_inputs_and_linked_response_files(self) -> None:
        self._saved_responses()
        self.assertEqual(self._main([str(self.repository)], argv=["--offline"]), 2)
        with patch.object(Path, "is_symlink", return_value=True):
            self.assertEqual(self._main([str(self.private)], argv=["--offline"]), 2)
        original_resolve = Path.resolve

        def redirected(path: Path, strict: bool = False) -> Path:
            if path.name == "zones.json":
                return self.repository / "private-response-body"
            return original_resolve(path, strict=strict)

        with patch.object(Path, "resolve", autospec=True, side_effect=redirected):
            self.assertEqual(self._main([str(self.private)], argv=["--offline"]), 2)
        self.assertNotIn("Shareable structural report", self.stdout.getvalue())
        self.send.assert_not_called()
        self._assert_private_output()

    def test_offline_and_live_modes_are_mutually_exclusive(self) -> None:
        with self.assertRaises(SystemExit) as stopped:
            self._main([], argv=["--live", "--offline"])
        self.assertEqual(stopped.exception.code, 2)
        self.send.assert_not_called()

    def test_bad_origin_is_rejected_before_credentials_can_be_sent(self) -> None:
        with patch.dict(os.environ, {"GARMIN_PERSONAL_API_BASE_URL": "https://example.invalid"}):
            self.assertEqual(self._main([]), 2)
        self.send.assert_not_called()
        self.assertIn("origin override", self.stderr.getvalue())
        self._assert_private_output()

    def test_missing_key_and_rejected_token_send_no_activity_requests(self) -> None:
        with patch.dict(os.environ, {"GARMIN_PERSONAL_API_KEY": ""}):
            self.assertEqual(self._main([]), 2)
        self.send.assert_not_called()
        self.auth_status = 401
        self.assertEqual(self._main(), 2)
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.calls[0][0], "POST")
        self.assertIn("Authentication failed with HTTP 401", self.stderr.getvalue())
        self._assert_private_output()

    def _check_stopping_status(self, status: int) -> None:
        self.failure_status = status
        self.assertEqual(self._main(), 1)
        self.assertEqual(len(self.calls), 2)
        report = self._report()
        self.assertIs(report["completed"], False)
        self.assertIs(report["has_http_errors"], True)
        self.assertIn(str(status), self.stdout.getvalue())
        self._assert_private_output()

    def test_rate_limit_stops_without_retry(self) -> None:
        self._check_stopping_status(429)
        self.assertIn('"retry_after_present": true', self.stdout.getvalue())

    def test_authentication_failure_stops_without_retry(self) -> None:
        self._check_stopping_status(401)

    def test_optional_404_is_explicit_not_a_successful_empty_result(self) -> None:
        self.failure_path = "/metrics-service/metrics/maxmet/daily/2030-01-02/2030-01-02"
        self.failure_status = 404
        self.assertEqual(self._main(), 1)
        self.assertEqual(len(self.calls), 11)
        self.assertIs(self._report()["completed"], True)
        self.assertIs(self._report()["has_http_errors"], True)
        self.assertIn('"http_status": 404', self.stdout.getvalue())
        self._assert_private_output()

    def test_redirect_is_blocked_without_following_it(self) -> None:
        self.failure_status = 302
        self.assertEqual(self._main(), 2)
        self.assertEqual(len(self.calls), 2)
        self.assertIn("Redirect rejected", self.stderr.getvalue())
        self._assert_private_output()

    def test_malformed_json_stops_without_printing_the_body(self) -> None:
        self.malformed_response = True
        self.assertEqual(self._main(), 2)
        self.assertEqual(len(self.calls), 2)
        self.assertIn("Discovery failed", self.stderr.getvalue())
        self.assertNotIn('"completed": true', self.stdout.getvalue())
        self._assert_private_output()

    def test_invalid_input_and_cache_do_not_start_network_requests(self) -> None:
        with self.subTest(case="empty directory"):
            self.assertEqual(self._main([""]), 2)
        with self.subTest(case="inside repository"):
            self.assertEqual(self._main([str(self.repository)]), 2)
        with self.subTest(case="invalid race ID"):
            self.assertEqual(
                self._main([str(self.private), "2030-01-02", "../private-response-body"]), 2
            )
        with self.subTest(case="invalid cache"):
            (self.private / "bearer-token.json").write_text(
                '{"access_token": "private-response-body"}', "utf-8"
            )
            self.assertEqual(self._main([str(self.private)]), 2)
        with self.subTest(case="oversized cache expiry"):
            (self.private / "bearer-token.json").write_text(
                json.dumps(
                    {
                        "access_token": "private-response-body",
                        "fingerprint": "synthetic-fingerprint",
                        "expires_at": 10**400,
                    }
                ),
                "utf-8",
            )
            self.assertEqual(self._main([str(self.private)]), 2)
        self.send.assert_not_called()
        self._assert_private_output()

    def test_transport_enforces_origin_and_request_budgets(self) -> None:
        plan = discovery.build_plan(discovery.date(2030, 1, 2), "123456789")
        with discovery.DiscoverySession(plan) as session:
            with self.assertRaisesRegex(discovery.DiscoveryError, "origin"):
                session.get("https://example.invalid/private-response-body")
            self.send.assert_not_called()
            for _ in range(10):
                session.get(discovery.ORIGIN + discovery.SEARCH_PATH)
            with self.assertRaisesRegex(discovery.DiscoveryError, "budget"):
                session.get(discovery.ORIGIN + discovery.SEARCH_PATH)
            session.post(discovery.ORIGIN + discovery.TOKEN_PATH)
            with self.assertRaisesRegex(discovery.DiscoveryError, "budget"):
                session.post(discovery.ORIGIN + discovery.TOKEN_PATH)
        self.assertEqual(len(self.calls), 11)


if __name__ == "__main__":
    unittest.main()
