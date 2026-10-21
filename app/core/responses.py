"""Envelope helpers: every response is `{success, code, message, data}`."""

from __future__ import annotations

from typing import Any

from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from app.core.metrics import metrics


def ok(data: Any = None, code: str = "OK", message: str = "OK") -> dict[str, Any]:
    """Build a success envelope (validated by the route's `response_model`).

    A specific `code` (SCAN_CREATED, INTAKE_LOGGED, REGISTERED, ...) is a business event and is counted."""
    if code != "OK":
        metrics.inc("events_total", event=code)
    return {"success": True, "code": code, "message": message, "data": data}


def fail(
    code: str,
    message: str,
    http_status: int,
    details: Any = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    """Build an error envelope response (counted by `code`)."""
    metrics.inc("app_errors_total", code=code)
    body = {"success": False, "code": code, "message": message, "data": None, "details": details}
    return JSONResponse(status_code=http_status, content=jsonable_encoder(body), headers=headers)
