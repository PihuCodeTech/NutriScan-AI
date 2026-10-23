"""In-process metrics (counters, latency histograms, gauges) rendered in the Prometheus text format.

The API runs as one process on purpose (see the Dockerfile), so plain in-memory counters are enough: no client
library, no push gateway. They reset on restart, which Prometheus' `rate()`/`increase()` handle.

Labels must stay low-cardinality and never carry user data: route *templates* (`/scans/{scan_id}`), response
codes, model names. Never user ids, emails, raw paths or message text."""

from __future__ import annotations

import os
import resource
import shutil
import sys
import threading
import time
from collections import defaultdict
from collections.abc import Callable, Iterable

Labels = tuple[tuple[str, str], ...]
Sample = tuple[str, Labels, float]

PREFIX = "nutriscan_"
# Seconds. AI calls take 2-20 s, plain CRUD a few ms, so the buckets span both.
LATENCY_BUCKETS = (0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 20.0, 30.0, 60.0)

# name (without prefix) → (type, help). Every metric must be declared here.
_DECLARED: dict[str, tuple[str, str]] = {
    "info": ("gauge", "Build and runtime info (always 1)."),
    "http_requests_total": ("counter", "HTTP requests by method, route template and status."),
    "http_request_duration_seconds": ("histogram", "HTTP request latency by method and route template."),
    "http_slow_requests_total": ("counter", "Requests slower than 3 s that made no Gemini call, by route template."),
    "app_errors_total": ("counter", "Error envelopes returned, by error code (e.g. AI_UNAVAILABLE, NOT_FOOD)."),
    "events_total": ("counter", "Business events: success envelopes with a specific code (SCAN_CREATED, ...)."),
    "unhandled_exceptions_total": ("counter", "Unexpected exceptions, by where they happened (http, task)."),
    "gemini_requests_total": ("counter", "Gemini call attempts by operation, model and outcome (ok, error)."),
    "gemini_request_duration_seconds": ("histogram", "Latency of successful Gemini calls."),
    "gemini_tokens_total": ("counter", "Gemini tokens used, by model and kind (prompt, output)."),
    "gemini_unavailable_total": ("counter", "AI requests that gave up after retries/fallback, by reason."),
    "classifier_failures_total": ("counter", "Food classifier predictions that failed (scan continued)."),
    "db_up": ("gauge", "1 if the last database check succeeded."),
    "db_check_duration_seconds": ("gauge", "Duration of the last database check."),
    "db_check_failures_total": ("counter", "Failed database checks."),
    "job_runs_total": ("counter", "Background job runs by job and outcome (ok, error)."),
    "job_last_success_timestamp_seconds": ("gauge", "Unix time of the job's last successful run."),
    "job_last_duration_seconds": ("gauge", "Duration of the job's last run."),
    "alerts_sent_total": ("counter", "Alert notifications sent, by alert and state (firing, resolved)."),
    "event_loop_lag_seconds": ("gauge", "Worst event-loop delay over the last monitoring interval."),
    "process_resident_memory_bytes": ("gauge", "Resident memory of the API process."),
    "process_cpu_seconds_total": ("counter", "CPU time used by the API process."),
    "process_open_fds": ("gauge", "Open file descriptors (Linux only)."),
    "process_uptime_seconds": ("gauge", "Seconds since the process started."),
    "container_memory_limit_bytes": ("gauge", "Container (cgroup v2) memory limit, when one is set."),
    "container_memory_usage_bytes": ("gauge", "Container (cgroup v2) memory usage, when a limit is set."),
    "storage_free_bytes": ("gauge", "Free disk space on the uploads volume."),
    "storage_total_bytes": ("gauge", "Size of the uploads volume."),
    "db_pool_checked_out": ("gauge", "Database connections currently in use."),
    "db_pool_size": ("gauge", "Configured database pool size."),
    "classifier_ready": ("gauge", "1 when the food classifier is loaded."),
}

_STARTED = time.time()


def _key(labels: dict[str, object]) -> Labels:
    return tuple(sorted((k, str(v)) for k, v in labels.items()))


class _Histogram:
    __slots__ = ("count", "counts", "sum")

    def __init__(self) -> None:
        self.counts = [0] * len(LATENCY_BUCKETS)
        self.sum = 0.0
        self.count = 0

    def observe(self, value: float) -> None:
        for i, bound in enumerate(LATENCY_BUCKETS):
            if value <= bound:
                self.counts[i] += 1
        self.sum += value
        self.count += 1


class Registry:
    """Thread-safe store of counters, gauges and histograms (classifier code runs in worker threads)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._values: dict[str, dict[Labels, float]] = defaultdict(dict)
        self._hists: dict[str, dict[Labels, _Histogram]] = defaultdict(dict)
        self._collectors: dict[str, Callable[[], Iterable[Sample]]] = {}

    def inc(self, name: str, value: float = 1.0, **labels: object) -> None:
        """Add to a counter."""
        assert name in _DECLARED, name
        key = _key(labels)
        with self._lock:
            series = self._values[name]
            series[key] = series.get(key, 0.0) + value

    def set(self, name: str, value: float, **labels: object) -> None:
        """Set a gauge."""
        assert name in _DECLARED, name
        with self._lock:
            self._values[name][_key(labels)] = float(value)

    def observe(self, name: str, seconds: float, **labels: object) -> None:
        """Record one latency sample in a histogram."""
        assert name in _DECLARED, name
        key = _key(labels)
        with self._lock:
            hist = self._hists[name].get(key)
            if hist is None:
                hist = self._hists[name][key] = _Histogram()
            hist.observe(seconds)

    def total(self, name: str, where: Callable[[dict[str, str]], bool] | None = None, **match: object) -> float:
        """Sum of a counter over every series whose labels include `match` and pass `where` (alert rules)."""
        want = {(k, str(v)) for k, v in match.items()}
        with self._lock:
            series = list(self._values.get(name, {}).items())
        return sum(v for labels, v in series if want <= set(labels) and (where is None or where(dict(labels))))

    def value(self, name: str, **labels: object) -> float | None:
        with self._lock:
            return self._values.get(name, {}).get(_key(labels))

    def add_collector(self, name: str, collector: Callable[[], Iterable[Sample]]) -> None:
        """Register (or replace) a function that yields (name, labels, value) gauges at scrape time."""
        self._collectors[name] = collector

    def reset(self) -> None:
        """Clear every recorded value (tests). Collectors stay."""
        with self._lock:
            self._values.clear()
            self._hists.clear()

    def render(self) -> str:
        """Prometheus text exposition format (version 0.0.4)."""
        samples: dict[str, list[tuple[Labels, float]]] = defaultdict(list)
        for collector in [process_samples, *self._collectors.values()]:
            try:
                for name, labels, value in collector():
                    samples[name].append((labels, value))
            except Exception:  # a broken collector must not break the scrape
                continue
        with self._lock:
            for name, series in self._values.items():
                samples[name].extend(series.items())
            hists = {name: dict(series) for name, series in self._hists.items()}

        lines: list[str] = []
        for name, (kind, help_text) in _DECLARED.items():
            if name not in samples and name not in hists:
                continue
            full = PREFIX + name
            lines += [f"# HELP {full} {help_text}", f"# TYPE {full} {kind}"]
            for labels, value in samples.get(name, []):
                lines.append(f"{full}{_fmt_labels(labels)} {_fmt_value(value)}")
            for labels, hist in hists.get(name, {}).items():
                for bound, count in zip(LATENCY_BUCKETS, hist.counts, strict=True):
                    lines.append(f"{full}_bucket{_fmt_labels((*labels, ('le', str(bound))))} {count}")
                lines.append(f"{full}_bucket{_fmt_labels((*labels, ('le', '+Inf')))} {hist.count}")
                lines.append(f"{full}_sum{_fmt_labels(labels)} {_fmt_value(hist.sum)}")
                lines.append(f"{full}_count{_fmt_labels(labels)} {hist.count}")
        return "\n".join(lines) + "\n"


def _fmt_labels(labels: Labels) -> str:
    if not labels:
        return ""
    escaped = (f'{k}="{v.replace(chr(92), chr(92) * 2).replace(chr(34), chr(92) + chr(34))}"' for k, v in labels)
    return "{" + ",".join(escaped) + "}"


def _fmt_value(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else repr(float(value))


# ----------------------------------------------------------------------------------------- resource usage


def resident_memory_bytes() -> int:
    """Current RSS on Linux; peak RSS elsewhere (macOS dev machines)."""
    try:
        with open("/proc/self/statm") as f:
            return int(f.read().split()[1]) * os.sysconf("SC_PAGE_SIZE")
    except (OSError, ValueError, IndexError):
        peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return peak if sys.platform == "darwin" else peak * 1024


def container_memory() -> tuple[int, int] | None:
    """(usage, limit) from cgroup v2, or None when there is no container memory limit."""
    try:
        with open("/sys/fs/cgroup/memory.max") as f:
            raw_limit = f.read().strip()
        with open("/sys/fs/cgroup/memory.current") as f:
            usage = int(f.read().strip())
    except (OSError, ValueError):
        return None
    if raw_limit == "max":
        return None
    return usage, int(raw_limit)


def disk_usage(path: str) -> tuple[int, int] | None:
    """(free, total) bytes of the filesystem holding `path`."""
    try:
        usage = shutil.disk_usage(path)
    except OSError:
        return None
    return usage.free, usage.total


def process_samples() -> Iterable[Sample]:
    yield "process_resident_memory_bytes", (), float(resident_memory_bytes())
    yield "process_cpu_seconds_total", (), time.process_time()
    yield "process_uptime_seconds", (), time.time() - _STARTED
    if os.path.isdir("/proc/self/fd"):
        yield "process_open_fds", (), float(len(os.listdir("/proc/self/fd")))
    mem = container_memory()
    if mem:
        yield "container_memory_usage_bytes", (), float(mem[0])
        yield "container_memory_limit_bytes", (), float(mem[1])


metrics = Registry()
