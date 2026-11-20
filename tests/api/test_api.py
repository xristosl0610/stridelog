"""Local API acceptance tests use synthetic database rows and no network."""

import json
import socket
import time
from collections.abc import Generator
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from stridelog.analytics import ANALYTICS_VERSION
from stridelog.api.app import create_app, openapi_schema
from stridelog.config import Settings
from stridelog.db.engine import database_engine, initialize_database
from stridelog.db.models import (
    Activity,
    ActivityAnalytics,
    ActivityAnnotation,
    ActivityRecord,
    DailyAnalytics,
    DailyWellness,
    HrvNight,
    SleepNight,
)
from stridelog.errors import StridelogError

pytestmark = pytest.mark.usefixtures("private_environment")
DAY = date(2030, 3, 31)
START = datetime(2030, 3, 31, 8, 0, tzinfo=UTC)
_ORIGINAL_CONNECT = socket.socket.connect


def _activity(activity_id: int, *, race: bool) -> Activity:
    return Activity(
        id=activity_id,
        name=f"Synthetic {activity_id}",
        activity_type="running",
        event_type=None,
        is_race=race,
        start_time_utc=START.isoformat(),
        utc_offset_s=0,
        end_utc_offset_s=0,
        local_date=DAY,
        distance_m=5_000.0 * activity_id,
        timer_time_s=1_800.0 * activity_id,
        elapsed_time_s=1_810.0 * activity_id,
        avg_hr_bpm=145.0,
        avg_cadence_spm=160.0,
        hr_source="unknown",
        hr_source_origin="unknown",
        dq_flags=[],
        source_checksums={"synthetic.fit": "a" * 64},
        garmin_metrics={},
        parser_version=1,
    )


def _seed(settings: Settings) -> None:
    initialize_database(settings.data_dir)
    engine = database_engine(settings.data_dir)
    try:
        with Session(engine) as session, session.begin():
            session.add_all([_activity(1, race=False), _activity(2, race=True)])
            session.add_all(
                [
                    ActivityAnnotation(
                        activity_id=2,
                        is_race_override=True,
                        race_name="Synthetic race",
                        official_time_s=3_600.0,
                        exclude_from_stats=False,
                        hr_invalid=False,
                        is_steady_run=False,
                        notes="Synthetic note",
                    ),
                    ActivityRecord(
                        activity_id=1,
                        record_index=0,
                        ts_utc=START.isoformat(),
                        distance_m=0.0,
                        lat_deg=37.0,
                        lon_deg=23.0,
                        altitude_m=10.0,
                        speed_mps=2.7,
                        heart_rate_bpm=140.0,
                        cadence_spm=160.0,
                    ),
                    ActivityRecord(
                        activity_id=1,
                        record_index=1,
                        ts_utc=START.isoformat(),
                        distance_m=5_000.0,
                        lat_deg=37.1,
                        lon_deg=23.1,
                        altitude_m=11.0,
                        speed_mps=2.8,
                        heart_rate_bpm=150.0,
                        cadence_spm=162.0,
                    ),
                    ActivityRecord(
                        activity_id=1,
                        record_index=2,
                        ts_utc=START.isoformat(),
                        distance_m=10_000.0,
                        lat_deg=37.2,
                        lon_deg=23.2,
                        altitude_m=12.0,
                        speed_mps=2.9,
                        heart_rate_bpm=155.0,
                        cadence_spm=164.0,
                    ),
                    ActivityRecord(
                        activity_id=1,
                        record_index=3,
                        ts_utc=START.isoformat(),
                        distance_m=15_000.0,
                        lat_deg=37.3,
                        lon_deg=23.3,
                        altitude_m=13.0,
                        speed_mps=3.0,
                        heart_rate_bpm=160.0,
                        cadence_spm=166.0,
                    ),
                    ActivityAnalytics(
                        activity_id=1,
                        input_signature="b" * 64,
                        algorithm_version=5,
                        metrics={
                            "best_efforts": [{"distance_m": 5_000.0, "duration_s": 1_800.0}],
                            "efficiency_factor": 1.2,
                        },
                    ),
                    ActivityAnalytics(
                        activity_id=2,
                        input_signature="c" * 64,
                        algorithm_version=5,
                        metrics={
                            "race_predictions": [
                                {
                                    "distance_m": 10_000.0,
                                    "riegel_time_s": 3_600.0,
                                    "vdot_time_s": None,
                                    "critical_speed_time_s": None,
                                }
                            ]
                        },
                    ),
                    DailyAnalytics(local_date=DAY, metrics={"ctl": 12.0, "atl": 20.0}),
                    DailyWellness(
                        local_date=DAY,
                        resting_hr_bpm=50.0,
                        steps=1_234.0,
                        stress_avg=20.0,
                        body_battery_high=80.0,
                        body_battery_low=10.0,
                        raw_path="synthetic.json",
                        raw_sha256="d" * 64,
                    ),
                    SleepNight(
                        local_date=DAY,
                        duration_s=28_800.0,
                        deep_s=7_200.0,
                        light_s=14_400.0,
                        rem_s=7_200.0,
                        awake_s=0.0,
                        score=None,
                        raw_path="synthetic.json",
                        raw_sha256="e" * 64,
                    ),
                    HrvNight(
                        local_date=DAY,
                        last_night_avg_ms=45.0,
                        raw_path="synthetic.json",
                        raw_sha256="f" * 64,
                    ),
                ]
            )
    finally:
        engine.dispose()


@pytest.fixture
def local_test_transport(monkeypatch: pytest.MonkeyPatch, private_environment: None) -> None:
    def connect_loopback(sock: socket.socket, address: tuple[str, int]) -> None:
        if address[0] not in {"127.0.0.1", "::1"}:
            pytest.fail("TestClient may connect only to a loopback socket.")
        _ORIGINAL_CONNECT(sock, address)

    monkeypatch.setattr(socket.socket, "connect", connect_loopback)


@pytest.fixture
def api_app(local_test_transport: None) -> FastAPI:
    settings = Settings()
    _seed(settings)
    return create_app(settings)


@pytest.fixture
def api_client(api_app: FastAPI) -> Generator[TestClient]:
    with TestClient(api_app, base_url="http://127.0.0.1:8000") as client:
        yield client


def test_activity_listing_details_stream_and_geojson(api_client: TestClient) -> None:
    page = api_client.get("/api/v1/activities", params={"page_size": 1}).json()
    assert page["total"] == 2
    assert page["items"][0]["id"] == 2
    assert api_client.get("/api/v1/activities", params={"race": True}).json()["total"] == 1
    detail = api_client.get("/api/v1/activities/1").json()
    assert detail["metrics"]["efficiency_factor"] == 1.2
    stream = api_client.get("/api/v1/activities/1/streams", params={"max_points": 2}).json()
    assert len(stream["points"]) == 2
    assert stream["points"][-1]["record_index"] == 3
    full_stream = api_client.get(
        "/api/v1/activities/1/streams",
        params={"full_resolution": True, "max_points": 2},
        headers={"accept-encoding": "gzip"},
    )
    assert full_stream.headers["content-encoding"] == "gzip"
    assert len(full_stream.json()["points"]) == 4
    route = api_client.get("/api/v1/activities/1/route").json()
    assert route["features"][0]["geometry"]["coordinates"] == [
        [23.0, 37.0],
        [23.1, 37.1],
        [23.2, 37.2],
        [23.3, 37.3],
    ]
    assert api_client.get("/api/v1/activities/999").status_code == 404


def test_analytics_and_wellness_endpoints(api_client: TestClient) -> None:
    volume = api_client.get("/api/v1/trends/volume", params={"period": "week"}).json()
    assert volume == [
        {
            "period_start": "2030-03-25",
            "distance_m": 15_000.0,
            "duration_s": 5_400.0,
            "activity_count": 2,
        }
    ]
    assert api_client.get("/api/v1/best-efforts", params={"distance_m": 5_000}).json() == [
        {
            "activity_id": 1,
            "local_date": "2030-03-31",
            "name": "Synthetic 1",
            "distance_m": 5_000.0,
            "duration_s": 1_800.0,
        }
    ]
    assert api_client.get("/api/v1/trends").json()[0]["pace_s_per_km"] == 360.0
    assert len(api_client.get("/api/v1/races").json()) == 1
    assert api_client.get("/api/v1/training-load").json()[0]["metrics"]["ctl"] == 12.0
    wellness = api_client.get("/api/v1/wellness").json()[0]
    assert wellness["resting_hr_bpm"] == 50.0
    assert wellness["sleep_duration_s"] == 28_800.0
    assert wellness["hrv_ms"] == 45.0
    assert len(api_client.get("/api/v1/predictions").json()) == 1


def test_stale_analytics_are_not_returned(api_client: TestClient) -> None:
    settings = Settings()
    engine = database_engine(settings.data_dir)
    try:
        with Session(engine) as session, session.begin():
            analytics = session.get(ActivityAnalytics, 1)
            assert analytics is not None
            analytics.algorithm_version = ANALYTICS_VERSION - 1
    finally:
        engine.dispose()

    assert api_client.get("/api/v1/activities/1").json()["metrics"] == {}
    assert api_client.get("/api/v1/trends").json()[0]["efficiency_factor"] is None
    assert api_client.get("/api/v1/best-efforts").json() == []


def test_annotation_changes_require_json_and_update_user_fields(api_client: TestClient) -> None:
    rejected = api_client.patch(
        "/api/v1/activities/1/annotation",
        content='{"notes":"private"}',
        headers={"content-type": "text/plain"},
    )
    assert rejected.status_code == 415
    updated = api_client.patch(
        "/api/v1/activities/1/annotation",
        json={"notes": "Synthetic note", "exclude_from_stats": True},
    )
    assert updated.status_code == 200
    assert updated.json()["excluded_from_stats"] is True
    assert updated.json()["notes"] == "Synthetic note"
    assert (
        api_client.get("/api/v1/activities", params={"include_excluded": True}).json()["total"] == 2
    )
    assert api_client.get("/api/v1/activities").json()["total"] == 1
    assert (
        api_client.patch("/api/v1/activities/1/annotation", json={"unknown": True}).status_code
        == 422
    )
    assert (
        api_client.patch(
            "/api/v1/activities/1/annotation", json={"official_time_s": 1_200}
        ).status_code
        == 422
    )
    promoted = api_client.patch(
        "/api/v1/activities/1/annotation",
        json={"is_race_override": True, "race_name": "Synthetic 5k", "official_time_s": 1_200},
    ).json()
    assert promoted["is_race"] is True
    cleared = api_client.patch(
        "/api/v1/activities/1/annotation", json={"is_race_override": None}
    ).json()
    assert cleared["is_race"] is False
    assert cleared["race_name"] is None


def test_sync_is_explicit_and_progress_can_be_polled(
    api_app: FastAPI, api_client: TestClient
) -> None:
    calls: list[date | None] = []

    def synthetic_runner(_settings: Settings, since: date | None) -> None:
        calls.append(since)

    api_app.state.sync_runner = synthetic_runner
    response = api_client.post("/api/v1/sync", json={"since": "2025-03-01"})
    assert response.status_code == 202
    job_id = response.json()["job_id"]
    state: dict[str, object] = {}
    for _ in range(100):
        state = api_client.get(f"/api/v1/sync/{job_id}").json()
        if state["status"] != "running":
            break
        time.sleep(0.01)
    assert state["status"] == "succeeded"
    assert calls == [date(2025, 3, 1)]

    def failing_runner(_settings: Settings, _since: date | None) -> None:
        raise StridelogError("Synthetic failure")

    api_app.state.sync_runner = failing_runner
    failed_job = api_client.post("/api/v1/sync", json={}).json()["job_id"]
    for _ in range(100):
        state = api_client.get(f"/api/v1/sync/{failed_job}").json()
        if state["status"] != "running":
            break
        time.sleep(0.01)
    assert state["status"] == "failed"
    assert "Synthetic failure" not in str(state["message"])


def test_local_request_security_and_get_revalidation(api_client: TestClient) -> None:
    assert (
        api_client.get("/api/v1/activities", headers={"host": "malicious.example"}).status_code
        == 400
    )
    assert (
        api_client.get(
            "/api/v1/activities", headers={"host": "attacker@127.0.0.1:8000"}
        ).status_code
        == 400
    )
    assert (
        api_client.get(
            "/api/v1/activities",
            headers={"origin": "https://malicious.example"},
        ).status_code
        == 403
    )
    first = api_client.get("/api/v1/activities")
    etag = first.headers["etag"]
    assert first.headers["cache-control"] == "private, no-cache"
    second = api_client.get("/api/v1/activities", headers={"if-none-match": etag})
    assert second.status_code == 304
    assert second.headers["etag"] == etag
    assert (
        api_client.patch(
            "/api/v1/activities/1/annotation", json={"notes": "Changed locally"}
        ).status_code
        == 200
    )
    changed = api_client.get("/api/v1/activities", headers={"if-none-match": etag})
    assert changed.status_code == 200
    assert changed.headers["etag"] != etag
    docs = api_client.get("/docs")
    assert docs.status_code == 200
    assert "/swagger-ui/swagger-ui-bundle.js" in docs.text
    assert "cdn.jsdelivr.net" not in docs.text
    assert api_client.get("/swagger-ui/swagger-ui-bundle.js").status_code == 200
    assert api_client.get("/swagger-ui/index.html").status_code == 404
    preflight = api_client.options(
        "/api/v1/activities/1/annotation",
        headers={
            "origin": "http://localhost:5173",
            "access-control-request-method": "PATCH",
            "access-control-request-headers": "content-type",
        },
    )
    assert preflight.status_code == 200
    assert preflight.headers["access-control-allow-origin"] == "http://localhost:5173"
    browser_get = api_client.get("/api/v1/activities", headers={"origin": "http://localhost:5173"})
    assert browser_get.headers["access-control-expose-headers"] == "ETag"


def test_checked_in_openapi_matches_application_schema() -> None:
    contract = Path(__file__).resolve().parents[2] / "openapi.json"
    assert json.loads(contract.read_text(encoding="utf-8")) == openapi_schema()
