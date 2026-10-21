"""AppError and the global exception handlers that render the error envelope."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.metrics import metrics
from app.core.responses import fail

logger = logging.getLogger("app.errors")


class AppError(Exception):
    """A handled, user-facing error. Rendered as the standard error envelope."""

    def __init__(self, code: str, message: str, http_status: int = 400, details: Any = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status
        self.details = details


# Convenience constructors for the common error codes
def not_found(what: str = "Resource") -> AppError:
    return AppError("NOT_FOUND", f"{what} not found.", 404)


def unauthorized(message: str = "Missing or invalid access token.") -> AppError:
    return AppError("UNAUTHORIZED", message, 401)


def ai_unavailable(
    message: str = "The AI service is temporarily unavailable. Please try again.", reason: str | None = None
) -> AppError:
    """503 AI_UNAVAILABLE. `reason` (auth, quota, model, timeout, network, ...) goes in `details.reason`."""
    return AppError("AI_UNAVAILABLE", message, 503, {"reason": reason} if reason else None)


_HTTP_CODES = {
    400: "BAD_REQUEST",
    401: "UNAUTHORIZED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    405: "METHOD_NOT_ALLOWED",
    413: "FILE_TOO_LARGE",
    415: "UNSUPPORTED_MEDIA_TYPE",
    429: "RATE_LIMITED",
}


def _clean_validation_errors(errors: list[dict[str, Any]]) -> list[dict[str, Any]]:
    cleaned = []
    for err in errors:
        cleaned.append(
            {
                "loc": [str(p) for p in err.get("loc", ())],
                "msg": str(err.get("msg", "")),
                "type": str(err.get("type", "")),
            }
        )
    return cleaned


def register_exception_handlers(app: FastAPI) -> None:
    """Attach handlers so every error — handled or not — uses the envelope."""

    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError) -> JSONResponse:
        return fail(exc.code, exc.message, exc.http_status, exc.details)

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        return fail("VALIDATION_ERROR", "Some fields are invalid.", 422, _clean_validation_errors(exc.errors()))

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = _HTTP_CODES.get(exc.status_code, "HTTP_ERROR")
        message = exc.detail if isinstance(exc.detail, str) else code.replace("_", " ").capitalize()
        if exc.status_code == 404:
            message = "Not found."
        elif exc.status_code == 405:
            message = "Method not allowed."
        return fail(code, message, exc.status_code, headers=getattr(exc, "headers", None))

    @app.exception_handler(RateLimitExceeded)
    async def _rate_limited(_: Request, exc: RateLimitExceeded) -> JSONResponse:
        return fail(
            "RATE_LIMITED",
            f"Too many requests. Limit: {exc.detail}. Please slow down and try again shortly.",
            429,
        )

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        metrics.inc("unhandled_exceptions_total", where="http")
        logger.exception("unhandled error on %s %s", request.method, request.url.path)
        return fail("INTERNAL_ERROR", "Something went wrong on our side. Please try again.", 500)
