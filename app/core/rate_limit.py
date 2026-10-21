"""Per-user (fallback per-IP) rate limiting for AI endpoints, using slowapi."""

from __future__ import annotations

from slowapi import Limiter
from slowapi.util import get_remote_address
from starlette.requests import Request

from app.core.config import get_settings
from app.core.security import decode_access_token


def rate_limit_key(request: Request) -> str:
    """Key by user id when a valid bearer token is present, otherwise by client IP."""
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        user_id = decode_access_token(auth[7:].strip())
        if user_id:
            return f"user:{user_id}"
    return f"ip:{get_remote_address(request)}"


def client_ip_key(request: Request) -> str:
    """Key by client IP only. For auth endpoints, where a bearer token must not buy a fresh bucket."""
    return f"ip:{get_remote_address(request)}"


def ai_limit() -> str:
    """Current AI limit string (read per request so it can be changed at runtime/tests)."""
    return get_settings().RATE_LIMIT_AI


def login_limit() -> str:
    return get_settings().RATE_LIMIT_LOGIN


def register_limit() -> str:
    return get_settings().RATE_LIMIT_REGISTER


limiter = Limiter(key_func=rate_limit_key, storage_uri="memory://", headers_enabled=False)
