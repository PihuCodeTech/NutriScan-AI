"""Production monitoring: background-job tracking, a watchdog that evaluates alert rules, webhook notifications.

Every rule is meant to be actionable (someone should do something when it fires). Checked every
MONITOR_INTERVAL_S (default 60 s):

  database_down        3 consecutive failed database checks (~3 min): DB down, paused or unreachable.
  server_errors        >= 5 HTTP 5xx and >= 5 % of requests in 5 min. 502 AI_BAD_RESPONSE / 503 AI_UNAVAILABLE
                       are Gemini's, not ours: excluded here, covered by the gemini_* rules.
  gemini_config        any AI request refused for auth / quota / model / not_configured in 5 min: fix the key,
                       billing or model name; retrying won't help.
  gemini_unavailable   >= 5 AI requests gave up after retries + fallback and >= 50 % of AI calls failed in 5 min.
  job_failed:<name>    the last run of a background job failed (resolves when a later run succeeds).
  disk_low             the uploads volume has < 10 % or < 1 GiB free.
  memory_high          the container uses > 90 % of its memory limit (cgroup v2 only).
  event_loop_blocked   the event loop stalled > 2 s in 3 consecutive intervals (blocking code on the loop).

A firing alert is logged at ERROR and posted to ALERT_WEBHOOK_URL (Slack and Discord incoming webhooks both
work) once, repeated every ALERT_REPEAT_MIN while it lasts, and followed by a RESOLVED message. Alert text holds
no user data. The process can't report its own death: pair this with an external uptime check on
/api/v1/health/ready (see README, "Monitoring")."""

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass, field
from urllib.parse import urlsplit

import httpx

from app.core.config import APP_VERSION, Settings
from app.core.metrics import Sample, container_memory, disk_usage, metrics
from app.db.session import check_database, pool_stats

logger = logging.getLogger("app.monitoring")

WINDOW_S = 300.0
DB_FAILURES_TO_ALERT = 3
SERVER_ERRORS_MIN, SERVER_ERROR_RATIO = 5, 0.05
AI_FAILURES_MIN, AI_FAILURE_RATIO = 5, 0.5
# AI_UNAVAILABLE reasons that need a human (key, billing, config), not patience.
AI_CONFIG_REASONS = frozenset({"auth", "quota", "model", "not_configured"})
DISK_FREE_MIN_RATIO, DISK_FREE_MIN_BYTES = 0.10, 1 << 30
MEMORY_MAX_RATIO = 0.90
LOOP_LAG_S, LOOP_LAG_INTERVALS = 2.0, 3
LAG_SAMPLE_S = 0.25
WEBHOOK_TIMEOUT_S = 5.0

Sender = Callable[[str], Awaitable[None]]


@dataclass
class JobStatus:
    runs: int = 0
    failures: int = 0
    last_ok: bool | None = None
    last_error: str | None = None
    last_success: float | None = None
    last_duration_s: float | None = None


@dataclass
class _AlertState:
    firing: bool = False
    since: float = 0.0
    last_sent: float = 0.0


@dataclass
class _Snapshot:
    at: float
    values: dict[str, float] = field(default_factory=dict)


def _server_error(labels: dict[str, str]) -> bool:
    # 502/503 here mean Gemini misbehaved (AI_BAD_RESPONSE / AI_UNAVAILABLE): not a bug in this server.
    status = int(labels.get("status", "0"))
    return status >= 500 and status not in (502, 503)


class Monitor:
    """Owns job status, alert state and the watchdog loop. One per app (`app.state.monitor`)."""

    def __init__(self, settings: Settings, *, sender: Sender | None = None) -> None:
        self.settings = settings
        self.jobs: dict[str, JobStatus] = {}
        self._alerts: dict[str, _AlertState] = {}
        self._snapshots: deque[_Snapshot] = deque()
        self._db_failures = 0
        self._lag_max = 0.0
        self._lag_streak = 0
        self._sender = sender or self._post_webhook
        self._classifier_status: Callable[[], str] = lambda: "disabled"

    # ------------------------------------------------------------------------------------------- jobs

    async def run_job(self, name: str, fn: Callable[[], Awaitable[object]]) -> bool:
        """Run one background job, recording outcome, duration and last success. Never raises."""
        status = self.jobs.setdefault(name, JobStatus())
        started = time.perf_counter()
        try:
            await fn()
        except Exception as exc:
            status.last_ok = False
            status.failures += 1
            status.last_error = type(exc).__name__
            metrics.inc("job_runs_total", job=name, outcome="error")
            logger.exception("background job failed", extra={"job": name})
        else:
            status.last_ok = True
            status.last_error = None
            status.last_success = time.time()
            metrics.inc("job_runs_total", job=name, outcome="ok")
            metrics.set("job_last_success_timestamp_seconds", status.last_success, job=name)
        finally:
            status.runs += 1
            status.last_duration_s = time.perf_counter() - started
            metrics.set("job_last_duration_seconds", status.last_duration_s, job=name)
        return bool(status.last_ok)

    async def run_every(self, name: str, interval_s: float, fn: Callable[[], Awaitable[object]]) -> None:
        """Run `fn` as job `name` every `interval_s` seconds (first run after one interval)."""
        while True:
            await asyncio.sleep(interval_s)
            await self.run_job(name, fn)

    # -------------------------------------------------------------------------------------- watchdog

    def watch_classifier(self, status: Callable[[], str]) -> None:
        self._classifier_status = status

    async def sample_loop_lag(self) -> None:
        """Measure how late the event loop wakes up; a large lag means something blocks it."""
        while True:
            started = time.perf_counter()
            await asyncio.sleep(LAG_SAMPLE_S)
            self._lag_max = max(self._lag_max, time.perf_counter() - started - LAG_SAMPLE_S)

    async def watch(self) -> None:
        """Watchdog loop: evaluate the alert rules every MONITOR_INTERVAL_S. Never raises."""
        self._take_snapshot()  # baseline, so the first window covers traffic since startup
        while True:
            await asyncio.sleep(self.settings.MONITOR_INTERVAL_S)
            try:
                await self.check_once()
            except Exception:
                metrics.inc("unhandled_exceptions_total", where="watchdog")
                logger.exception("monitoring check failed")

    async def check_once(self) -> None:
        """Evaluate every alert rule once."""
        await self._check_database()
        self._take_snapshot()
        await self._check_rates()
        for name, status in self.jobs.items():
            await self._alert(
                f"job_failed:{name}",
                status.last_ok is False,
                f"Background job '{name}' failed ({status.last_error}). See logs for job={name}.",
            )
        await self._check_resources()

    async def _check_database(self) -> None:
        try:
            elapsed = await check_database()
        except Exception as exc:
            self._db_failures += 1
            metrics.inc("db_check_failures_total")
            metrics.set("db_up", 0)
            logger.warning("database check failed", extra={"error": type(exc).__name__, "streak": self._db_failures})
        else:
            self._db_failures = 0
            metrics.set("db_up", 1)
            metrics.set("db_check_duration_seconds", elapsed)
        await self._alert(
            "database_down",
            self._db_failures >= DB_FAILURES_TO_ALERT,
            f"Database unreachable for {self._db_failures} consecutive checks. Check the DB host / Supabase "
            "project status and DATABASE_URL.",
        )

    def _take_snapshot(self) -> None:
        now = time.monotonic()
        self._snapshots.append(
            _Snapshot(
                now,
                {
                    "requests": metrics.total("http_requests_total"),
                    "server_errors": metrics.total("http_requests_total", where=_server_error),
                    "ai_ok": metrics.total("gemini_requests_total", outcome="ok"),
                    "ai_config": metrics.total(
                        "gemini_unavailable_total", where=lambda labels: labels.get("reason") in AI_CONFIG_REASONS
                    ),
                    "ai_down": metrics.total(
                        "gemini_unavailable_total",
                        where=lambda labels: labels.get("reason") not in AI_CONFIG_REASONS,
                    ),
                },
            )
        )
        while len(self._snapshots) > 2 and now - self._snapshots[1].at >= WINDOW_S:
            self._snapshots.popleft()

    def _window(self) -> dict[str, float]:
        """Counter increases between the oldest snapshot in the window and the newest."""
        first, last = self._snapshots[0], self._snapshots[-1]
        return {k: last.values[k] - first.values.get(k, 0.0) for k in last.values}

    async def _check_rates(self) -> None:
        d = self._window()
        requests, errors = d["requests"], d["server_errors"]
        await self._alert(
            "server_errors",
            errors >= SERVER_ERRORS_MIN and errors >= SERVER_ERROR_RATIO * max(requests, 1),
            f"{int(errors)} server errors (HTTP 5xx) out of {int(requests)} requests in the last 5 min. "
            "Search the logs for level=ERROR.",
        )
        await self._alert(
            "gemini_config",
            d["ai_config"] > 0 or (self.settings.APP_ENV == "prod" and self.settings.gemini_status == "missing"),
            "Gemini is refusing requests for a reason retrying won't fix (API key, quota/billing or model name). "
            "Search the logs for 'gemini unavailable' and run scripts/smoke_gemini.py.",
        )
        down, ok = d["ai_down"], d["ai_ok"]
        await self._alert(
            "gemini_unavailable",
            down >= AI_FAILURES_MIN and down >= AI_FAILURE_RATIO * (down + ok),
            f"{int(down)} AI requests failed after retries and fallback in the last 5 min "
            f"({int(ok)} Gemini calls succeeded). Check https://status.cloud.google.com and the logs.",
        )

    async def _check_resources(self) -> None:
        disk = disk_usage(self.settings.STORAGE_DIR)
        if disk:
            free, total = disk
            await self._alert(
                "disk_low",
                free < DISK_FREE_MIN_BYTES or free < DISK_FREE_MIN_RATIO * total,
                f"Uploads volume has {free / (1 << 30):.1f} GiB free of {total / (1 << 30):.1f} GiB.",
            )
        mem = container_memory()
        if mem:
            used, limit = mem
            await self._alert(
                "memory_high",
                used > MEMORY_MAX_RATIO * limit,
                f"Container memory at {used / limit:.0%} of its {limit >> 20} MiB limit.",
            )
        lag, self._lag_max = self._lag_max, 0.0
        metrics.set("event_loop_lag_seconds", lag)
        self._lag_streak = self._lag_streak + 1 if lag > LOOP_LAG_S else 0
        await self._alert(
            "event_loop_blocked",
            self._lag_streak >= LOOP_LAG_INTERVALS,
            f"Event loop stalled up to {lag:.1f} s in {self._lag_streak} consecutive checks: requests queue up. "
            "Look for CPU-bound work outside run_in_threadpool.",
        )

    # ---------------------------------------------------------------------------------------- alerts

    @property
    def firing(self) -> list[str]:
        return sorted(name for name, state in self._alerts.items() if state.firing)

    async def _alert(self, name: str, firing: bool, summary: str) -> None:
        """Track one rule's state; notify on start, every ALERT_REPEAT_MIN while firing, and on resolve."""
        state = self._alerts.setdefault(name, _AlertState())
        now = time.time()
        if firing:
            repeat = self.settings.ALERT_REPEAT_MIN * 60
            if not state.firing:
                state.firing, state.since = True, now
            elif repeat <= 0 or now - state.last_sent < repeat:
                return
            state.last_sent = now
            logger.error("alert firing", extra={"alert": name, "summary": summary})
            await self._notify(name, "firing", f"🔴 [{self._where()}] {name}: {summary}")
        elif state.firing:
            minutes = round((now - state.since) / 60)
            state.firing = False
            logger.warning("alert resolved", extra={"alert": name, "minutes": minutes})
            await self._notify(name, "resolved", f"✅ [{self._where()}] RESOLVED {name} (after ~{minutes} min)")

    def _where(self) -> str:
        host = urlsplit(self.settings.PUBLIC_BASE_URL).hostname or "nutriscan"
        return f"{self.settings.APP_ENV} {host}"

    async def _notify(self, name: str, state: str, text: str) -> None:
        if not self.settings.ALERT_WEBHOOK_URL and self._sender == self._post_webhook:
            return  # no webhook configured: the ERROR log line is the alert
        try:
            await self._sender(text)
            metrics.inc("alerts_sent_total", alert=name.split(":")[0], state=state)
        except Exception as exc:
            # Never log the URL: webhook URLs are secrets.
            logger.warning("alert webhook failed", extra={"alert": name, "error": type(exc).__name__})

    async def _post_webhook(self, text: str) -> None:
        # "text" is read by Slack (and most chat webhooks), "content" by Discord; each ignores the other.
        async with httpx.AsyncClient(timeout=WEBHOOK_TIMEOUT_S) as client:
            resp = await client.post(self.settings.ALERT_WEBHOOK_URL, json={"text": text, "content": text})
            resp.raise_for_status()

    # ------------------------------------------------------------------------------- scrape-time gauges

    def collect(self) -> Iterable[Sample]:
        """Gauges computed at scrape time: build info, storage, DB pool, classifier."""
        yield "info", (("env", self.settings.APP_ENV), ("version", APP_VERSION)), 1.0
        disk = disk_usage(self.settings.STORAGE_DIR)
        if disk:
            yield "storage_free_bytes", (), float(disk[0])
            yield "storage_total_bytes", (), float(disk[1])
        pool = pool_stats()
        if pool:
            yield "db_pool_checked_out", (), float(pool[0])
            yield "db_pool_size", (), float(pool[1])
        yield "classifier_ready", (), 1.0 if self._classifier_status() == "loaded" else 0.0


def report_crash(task: asyncio.Task[None]) -> None:
    """Done-callback for background tasks: a task that dies with an exception is logged and counted."""
    if task.cancelled() or task.exception() is None:
        return
    metrics.inc("unhandled_exceptions_total", where="task")
    logger.error("background task crashed", extra={"task": task.get_name()}, exc_info=task.exception())
