"""Envelope helpers: every response is `{success, code, message, data}`."""

from __future__ import annotations

from typing import Any

from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse


def ok(data: Any = None, code: str = "OK", message: str = "OK") -> dict[str, Any]:
    """Build a success envelope (validated by the route's `response_model`)."""
    return {"success": True, "code": code, "message": message, "data": data}


def fail(
    code: str,
    message: str,
    http_status: int,
    details: Any = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    """Build an error envelope response."""
    body = {"success": False, "code": code, "message": message, "data": None, "details": details}
    return JSONResponse(status_code=http_status, content=jsonable_encoder(body), headers=headers)
