"""OpenAPI helpers: documented error responses per route."""

from __future__ import annotations

from typing import Any

from app.schemas.common import ErrorEnvelope

_ERRORS: dict[str, tuple[int, str]] = {
    "VALIDATION_ERROR": (422, "Some fields are invalid."),
    "UNAUTHORIZED": (401, "Missing or invalid access token."),
    "INVALID_CREDENTIALS": (401, "Incorrect email or password."),
    "EMAIL_TAKEN": (409, "An account with this email already exists."),
    "NOT_FOUND": (404, "Scan not found."),
    "INVALID_IMAGE": (400, "The file is not a valid JPEG, PNG or WebP image."),
    "FILE_TOO_LARGE": (413, "Image is larger than 8 MB."),
    "NOT_FOOD": (422, "No food detected in the image."),
    "EMPTY_MESSAGE": (400, "Type a message or attach a photo."),
    "ALREADY_LOGGED": (409, "This scan is already logged to your intake."),
    "RATE_LIMITED": (429, "Too many requests. Please slow down and try again shortly."),
    "AI_UNAVAILABLE": (503, "The AI service is temporarily unavailable. Please try again."),
    "AI_BAD_RESPONSE": (502, "The AI returned an invalid response. Please try again."),
}


def errors(*codes: str) -> dict[int | str, dict[str, Any]]:
    """Build a FastAPI `responses=` mapping with example error envelopes, grouped by status."""
    by_status: dict[int, dict[str, Any]] = {}
    for code in codes:
        status, message = _ERRORS[code]
        entry = by_status.setdefault(
            status, {"model": ErrorEnvelope, "description": "", "content": {"application/json": {"examples": {}}}}
        )
        entry["description"] = ", ".join(filter(None, [entry["description"], code]))
        entry["content"]["application/json"]["examples"][code] = {
            "summary": code,
            "value": {"success": False, "code": code, "message": message, "data": None, "details": None},
        }
    return dict(by_status)


AUTH = ("UNAUTHORIZED",)
AI = ("RATE_LIMITED", "AI_UNAVAILABLE", "AI_BAD_RESPONSE")
