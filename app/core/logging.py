"""Structured (JSON-lines) logging with secret redaction, and a request-id / access-log / metrics middleware."""

from __future__ import annotations

import json
import logging
import re
import time
import uuid
from contextvars import ContextVar
from datetime import UTC, datetime

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.metrics import metrics

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)
user_id_var: ContextVar[str | None] = ContextVar("user_id", default=None)

_RESERVED = set(logging.makeLogRecord({}).__dict__) | {"message", "asctime"}

# Last line of defence: code should never log these, but an exception message or a third-party log line might.
_SECRET_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"AIza[0-9A-Za-z_\-]{20,}"), "[REDACTED_API_KEY]"),  # Google API keys
    (re.compile(r"\bAQ\.[0-9A-Za-z_\-.]{20,}"), "[REDACTED_API_KEY]"),  # Google AI Studio "AQ." keys
    (re.compile(r"(?i)\bbearer\s+[0-9A-Za-z_\-.=]+"), "Bearer [REDACTED]"),
    (re.compile(r"\beyJ[0-9A-Za-z_\-]+\.[0-9A-Za-z_\-]+\.[0-9A-Za-z_\-]+"), "[REDACTED_JWT]"),
    (re.compile(r"(://[^:/@\s]+):[^@/\s]+@"), r"\1:[REDACTED]@"),  # passwords in connection URLs
    (re.compile(r"(?i)\b(password|passwd|secret|api_key|token|sig)=[^&\s\"']+"), r"\1=[REDACTED]"),
]

# Probe endpoints polled every few seconds: counted in metrics, but only logged when they fail.
_QUIET_PATHS = frozenset({"/metrics", "/api/v1/health", "/api/v1/health/ready"})


def route_template(scope: Scope) -> str | None:
    """Full route template of the matched route, e.g. `/api/v1/scans/{scan_id}` (None if nothing matched).

    `scope["route"].path` is relative to the innermost router, so the static prefix is recovered from the real
    path: fill the route's parameters back in and keep what comes before them."""
    route = scope.get("route")
    template = getattr(route, "path_format", None) or getattr(route, "path", None)
    if not template:
        return None
    path: str = scope.get("path", "")
    try:
        concrete = template.format(**{k: str(v) for k, v in (scope.get("path_params") or {}).items()})
    except (KeyError, IndexError, ValueError):
        return template
    return path[: -len(concrete)] + template if concrete and path.endswith(concrete) else template


def redact(text: str) -> str:
    """Mask API keys, bearer tokens, JWTs and URL/query-string secrets in a log string."""
    for pattern, replacement in _SECRET_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


class JsonFormatter(logging.Formatter):
    """One JSON object per line with request/user ids and any `extra=` fields."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "msg": redact(record.getMessage()),
        }
        rid = request_id_var.get()
        if rid:
            payload["request_id"] = rid
        uid = user_id_var.get()
        if uid:
            payload["user_id"] = uid
        for key, value in record.__dict__.items():
            if key not in _RESERVED and not key.startswith("_"):
                payload[key] = redact(value) if isinstance(value, str) else value
        if record.exc_info:
            payload["exc"] = redact(self.formatException(record.exc_info))
        return json.dumps(payload, default=str, ensure_ascii=False)


def configure_logging(level: str = "INFO") -> None:
    """Install the JSON formatter on the root logger (idempotent)."""
    root = logging.getLogger()
    root.setLevel(level.upper())
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root.handlers = [handler]
    for noisy in ("httpx", "httpcore", "urllib3", "google_genai", "aiosqlite"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").disabled = True  # replaced by our access log


class RequestContextMiddleware:
    """Pure-ASGI middleware: assigns a request id, logs method/route/status/latency and records HTTP metrics."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app
        self.logger = logging.getLogger("app.access")

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers") or [])
        incoming = headers.get(b"x-request-id", b"").decode("latin-1")[:64]
        rid = incoming or uuid.uuid4().hex[:16]
        token = request_id_var.set(rid)
        user_token = user_id_var.set(None)
        start = time.perf_counter()
        status = 500

        async def send_wrapper(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                message.setdefault("headers", [])
                message["headers"].append((b"x-request-id", rid.encode("latin-1")))
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            elapsed = time.perf_counter() - start
            method = scope.get("method")
            path = scope.get("path")
            # The route *template* (e.g. /api/v1/scans/{scan_id}) keeps metric labels low-cardinality.
            route = route_template(scope)
            metrics.inc("http_requests_total", method=method, route=route or "unmatched", status=status)
            metrics.observe("http_request_duration_seconds", elapsed, method=method, route=route or "unmatched")
            if path not in _QUIET_PATHS or status >= 400:
                self.logger.info(
                    "request",
                    extra={
                        "method": method,
                        "path": path,
                        "route": route,
                        "status": status,
                        "latency_ms": round(elapsed * 1000, 1),
                    },
                )
            user_id_var.reset(user_token)
            request_id_var.reset(token)
