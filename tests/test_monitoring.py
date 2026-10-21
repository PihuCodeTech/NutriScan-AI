"""Monitoring: /metrics, readiness, log redaction, Gemini/job metrics and the watchdog's alert rules."""

from __future__ import annotations

import json
import logging

import pytest

from app.core.errors import AppError
from app.core.logging import JsonFormatter, redact
from app.core.metrics import metrics
from app.db.session import get_db
from app.services import monitoring
from app.services.llm.mock_client import rajma_chawal_fixture
from app.services.monitoring import Monitor
from tests.conftest import create_scan, make_jpeg, register_user
from tests.test_llm_client import _client, _client_error, _resp

TOKEN = "metrics-token-for-tests"


@pytest.fixture(autouse=True)
def _fresh_metrics():
    metrics.reset()


@pytest.fixture
def metrics_on(settings, monkeypatch):
    monkeypatch.setattr(settings, "METRICS_TOKEN", TOKEN)


async def _scrape(client) -> str:
    r = await client.get("/metrics", headers={"Authorization": f"Bearer {TOKEN}"})
    assert r.status_code == 200, r.text
    return r.text


# ---------------------------------------------------------------------------------------- /metrics


async def test_metrics_disabled_without_token(client):
    r = await client.get("/metrics")
    assert r.status_code == 404
    assert r.json()["code"] == "NOT_FOUND"


async def test_metrics_requires_the_token(client, metrics_on):
    assert (await client.get("/metrics")).status_code == 401
    assert (await client.get("/metrics", headers={"Authorization": "Bearer wrong"})).status_code == 401


async def test_metrics_track_requests_events_and_errors_without_user_data(client, metrics_on):
    email = "privacy-check@example.com"
    r = await client.post("/api/v1/auth/register", json={"email": email, "password": "password123", "name": "Asha"})
    user_id = r.json()["data"]["user"]["id"]
    headers = {"Authorization": f"Bearer {r.json()['data']['access_token']}"}
    assert (await create_scan(client, headers, make_jpeg())).status_code == 201
    await client.get("/api/v1/scans/does-not-exist", headers=headers)
    await client.get("/api/v1/users/me")  # no token

    text = await _scrape(client)
    assert 'nutriscan_http_requests_total{method="POST",route="/api/v1/scans",status="201"} 1' in text
    assert 'route="/api/v1/scans/{scan_id}",status="404"' in text
    assert 'nutriscan_events_total{event="REGISTERED"} 1' in text
    assert 'nutriscan_events_total{event="SCAN_CREATED"} 1' in text
    assert 'nutriscan_app_errors_total{code="UNAUTHORIZED"} 1' in text
    assert "nutriscan_http_request_duration_seconds_bucket" in text
    assert "nutriscan_process_resident_memory_bytes" in text
    assert "nutriscan_storage_free_bytes" in text
    assert 'nutriscan_job_runs_total{job="guest_cleanup",outcome="ok"} 1' in text
    assert email not in text and user_id not in text and "does-not-exist" not in text


# ---------------------------------------------------------------------------------------- readiness


async def test_ready_ok(client):
    r = await client.get("/api/v1/health/ready")
    assert r.status_code == 200
    assert r.json()["data"]["db"] == "ok"


async def test_ready_is_503_when_database_is_down(app, client):
    class BrokenSession:
        async def execute(self, *_args, **_kwargs):
            raise ConnectionRefusedError("db down")

    async def broken_db():
        yield BrokenSession()

    app.dependency_overrides[get_db] = broken_db
    r = await client.get("/api/v1/health/ready")
    assert r.status_code == 503
    assert r.json()["code"] == "NOT_READY" and r.json()["data"] is None
    assert r.json()["details"]["db"] == "error"
    # Liveness stays 200, so a database outage doesn't get the container restarted.
    assert (await client.get("/api/v1/health")).status_code == 200


# ---------------------------------------------------------------------------------------- redaction


@pytest.mark.parametrize(
    ("raw", "secret"),
    [
        ("key=AIzaSyA1234567890abcdefghijklmnopqrstuv failed", "AIzaSyA1234567890abcdefghijklmnopqrstuv"),
        ("Authorization: Bearer abc.def-ghi", "abc.def-ghi"),
        ("token eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.c2lnbmF0dXJl", "eyJzdWIiOiIxIn0"),
        ("postgresql+asyncpg://postgres.ref:hunter2pass@db.example.com:5432/postgres", "hunter2pass"),
        ("/media/a.jpg?exp=1&sig=deadbeefcafe", "deadbeefcafe"),
        ("login password=Sup3rSecret!", "Sup3rSecret!"),
    ],
)
def test_redact_masks_secrets(raw, secret):
    assert secret not in redact(raw)


def test_json_log_lines_are_redacted():
    record = logging.makeLogRecord(
        {"msg": "connect to %s", "args": ("postgresql://u:pw123456@h/db",), "levelname": "ERROR", "name": "t"}
    )
    record.detail = "Bearer abcdefghijkl"
    line = json.loads(JsonFormatter().format(record))
    assert "pw123456" not in line["msg"] and "abcdefghijkl" not in line["detail"]


# ---------------------------------------------------------------------------------------- Gemini metrics


async def test_gemini_success_and_give_up_are_counted():
    client, _ = _client({"primary-model": [_resp(parsed=rajma_chawal_fixture())]})
    await client.estimate_from_text("rajma chawal", user_ctx="")
    assert metrics.total("gemini_requests_total", model="primary-model", outcome="ok") == 1
    assert metrics.total("gemini_tokens_total", kind="prompt") == 10

    client, _ = _client({"primary-model": [_client_error(403)], "fallback-model": [_resp(text="{}")]})
    with pytest.raises(AppError):
        await client.estimate_from_text("rice", user_ctx="")
    assert metrics.total("gemini_requests_total", outcome="error") == 1
    assert metrics.total("gemini_unavailable_total", reason="auth") == 1


# ---------------------------------------------------------------------------------------- watchdog


class Recorder:
    def __init__(self) -> None:
        self.sent: list[str] = []

    async def __call__(self, text: str) -> None:
        self.sent.append(text)


@pytest.fixture
def monitor(settings, monkeypatch) -> tuple[Monitor, Recorder]:
    async def db_ok(*_args):
        return 0.001

    monkeypatch.setattr(monitoring, "check_database", db_ok)
    recorder = Recorder()
    return Monitor(settings, sender=recorder), recorder


async def test_database_down_fires_once_then_resolves(monitor, monkeypatch):
    mon, sent = monitor

    async def db_down(*_args):
        raise ConnectionRefusedError

    monkeypatch.setattr(monitoring, "check_database", db_down)
    for _ in range(monitoring.DB_FAILURES_TO_ALERT - 1):
        await mon.check_once()
    assert sent.sent == []  # one or two blips are not worth waking anyone
    await mon.check_once()
    await mon.check_once()
    assert len(sent.sent) == 1 and "database_down" in sent.sent[0]
    assert mon.firing == ["database_down"]

    async def db_ok(*_args):
        return 0.001

    monkeypatch.setattr(monitoring, "check_database", db_ok)
    await mon.check_once()
    assert "RESOLVED database_down" in sent.sent[-1]
    assert mon.firing == []


async def test_server_error_rate_alert(monitor):
    mon, sent = monitor
    await mon.check_once()  # baseline snapshot
    for _ in range(50):
        metrics.inc("http_requests_total", method="GET", route="/api/v1/x", status=200)
    for _ in range(3):
        metrics.inc("http_requests_total", method="GET", route="/api/v1/x", status=500)
    for _ in range(10):  # Gemini's errors are not counted as ours
        metrics.inc("http_requests_total", method="POST", route="/api/v1/scans", status=503)
    await mon.check_once()
    assert "server_errors" not in mon.firing

    for _ in range(3):
        metrics.inc("http_requests_total", method="GET", route="/api/v1/x", status=500)
    await mon.check_once()
    assert "server_errors" in mon.firing
    assert "6 server errors" in sent.sent[-1]


async def test_gemini_rules(monitor):
    mon, _ = monitor
    await mon.check_once()
    metrics.inc("gemini_unavailable_total", op="analyze_food_image", reason="quota")
    for _ in range(5):
        metrics.inc("gemini_unavailable_total", op="chat_turn", reason="timeout")
    metrics.inc("gemini_requests_total", 2, op="chat_turn", model="m", outcome="ok")
    await mon.check_once()
    assert mon.firing == ["gemini_config", "gemini_unavailable"]


async def test_failed_job_alerts_until_it_succeeds(monitor):
    mon, sent = monitor

    async def boom():
        raise RuntimeError("nope")

    async def fine():
        return None

    assert await mon.run_job("guest_cleanup", boom) is False
    await mon.check_once()
    assert mon.firing == ["job_failed:guest_cleanup"]
    assert "RuntimeError" in sent.sent[-1]
    assert await mon.run_job("guest_cleanup", fine) is True
    await mon.check_once()
    assert mon.firing == []
    assert metrics.value("job_last_success_timestamp_seconds", job="guest_cleanup")


async def test_disk_low_alert(monitor, monkeypatch):
    mon, _ = monitor
    monkeypatch.setattr(monitoring, "disk_usage", lambda _path: (500 << 20, 100 << 30))
    await mon.check_once()
    assert "disk_low" in mon.firing


async def test_firing_alert_is_repeated_only_after_the_repeat_interval(monitor, monkeypatch):
    mon, sent = monitor
    monkeypatch.setattr(monitoring, "disk_usage", lambda _path: (0, 100 << 30))
    clock = [1_000_000.0]
    monkeypatch.setattr(monitoring.time, "time", lambda: clock[0])
    await mon.check_once()
    await mon.check_once()
    assert len(sent.sent) == 1
    clock[0] += mon.settings.ALERT_REPEAT_MIN * 60 + 1
    await mon.check_once()
    assert len(sent.sent) == 2


async def test_no_webhook_means_alerts_are_only_logged(settings, monkeypatch, caplog):
    async def db_ok(*_args):
        return 0.001

    monkeypatch.setattr(monitoring, "check_database", db_ok)
    monkeypatch.setattr(monitoring, "disk_usage", lambda _path: (0, 100 << 30))
    mon = Monitor(settings)  # ALERT_WEBHOOK_URL is empty in tests: nothing is posted
    with caplog.at_level(logging.ERROR, logger="app.monitoring"):
        await mon.check_once()
    assert any(r.getMessage() == "alert firing" and r.alert == "disk_low" for r in caplog.records)
    assert metrics.total("alerts_sent_total") == 0


async def test_register_user_helper_still_works(client):
    # Guard: counting events in ok() must not change any response.
    headers = await register_user(client)
    assert (await client.get("/api/v1/users/me", headers=headers)).json()["success"] is True
