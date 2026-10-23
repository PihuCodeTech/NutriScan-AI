"""Gemini reliability policy: classify a failure, map it to a user-facing error, and small diagnostics.

Kept separate from the Gemini calls in `gemini_client.py` so the retry/fallback behaviour can be read, tested
and changed on its own (e.g. when swapping models or providers). Pure functions over exception objects, with no
network, no SDK client."""

from __future__ import annotations

import asyncio

import httpx
from google.genai import errors as genai_errors

from app.core.errors import AppError, ai_unavailable

# Pause before retrying the primary model once, before falling back.
RETRY_DELAY_S = 1.5

_KEY_ERROR_MARKERS = ("api key", "api_key", "unauthenticated", "credential", "permission_denied")


def is_key_problem(exc: BaseException | None) -> bool:
    """True when Gemini rejected the API key itself (invalid, revoked, wrong project/mode, no permission)."""
    if not isinstance(exc, genai_errors.ClientError):
        return False
    if exc.code in (401, 403):
        return True
    if exc.code == 400:
        text = f"{exc.status or ''} {exc.message or ''} {getattr(exc, 'details', '') or ''}".lower()
        return any(marker in text for marker in _KEY_ERROR_MARKERS)
    return False


def classify(exc: BaseException) -> str:
    """'retry' (transient, same model), 'fallback' (try the other model), or 'fatal' (give up)."""
    if isinstance(exc, (asyncio.TimeoutError, TimeoutError)):
        # The model is too slow right now: waiting another full timeout on it rarely helps.
        return "fallback"
    if isinstance(exc, httpx.TransportError):
        return "retry"
    if isinstance(exc, genai_errors.ServerError):
        # 503 UNAVAILABLE ("model is experiencing high demand") and 504 DEADLINE_EXCEEDED mean the model is
        # overloaded or slow; retrying it 1.5 s later rarely helps. Other 5xx are transient: retry once.
        return "fallback" if exc.code in (503, 504) else "retry"
    if isinstance(exc, genai_errors.ClientError):
        if exc.code == 429:
            # A per-day quota won't come back in 1.5 s; a per-minute one might.
            return "fallback" if "perday" in str(exc).lower() else "retry"
        if is_key_problem(exc):
            return "fatal"  # the fallback model would reject the same key
        if exc.code in (400, 404):
            # Model not found, or a request this model can't serve (e.g. an unsupported schema/feature):
            # the fallback model may still work.
            return "fallback"
        return "fatal"
    if isinstance(exc, genai_errors.APIError):
        return "retry" if (exc.code or 0) >= 500 else "fatal"
    return "retry"


def should_cool_down(exc: BaseException) -> bool:
    """True when the failure says the *model* is struggling (overloaded, slow, rate-limited, unreachable or
    missing), so other requests should go to the other model for a while. A 400 about one request is not."""
    if isinstance(exc, (asyncio.TimeoutError, TimeoutError, httpx.TransportError, genai_errors.ServerError)):
        return True
    return isinstance(exc, genai_errors.ClientError) and exc.code in (404, 429)


def unavailable(exc: BaseException | None) -> AppError:
    """Turn the last Gemini failure into a 503 AI_UNAVAILABLE that says what actually went wrong.

    `details.reason` is one of: auth, quota, model, timeout, network, bad_request, unavailable.
    Messages never contain the key.
    """
    if is_key_problem(exc):
        return ai_unavailable(
            "The Gemini API rejected the server's API key. Check GEMINI_API_KEY (and GEMINI_USE_VERTEX) in the "
            "backend's .env file, then restart the server.",
            reason="auth",
        )
    if isinstance(exc, genai_errors.ClientError) and exc.code == 429:
        return ai_unavailable(
            "The Gemini API quota or rate limit for this key was reached. Wait a minute and try again, or check "
            "the key's limits in Google AI Studio.",
            reason="quota",
        )
    if isinstance(exc, genai_errors.ClientError) and exc.code == 404:
        return ai_unavailable(
            "The configured Gemini model isn't available for this key. Run scripts/smoke_gemini.py to list the "
            "available models, then update GEMINI_MODEL / GEMINI_FALLBACK_MODEL in .env.",
            reason="model",
        )
    if isinstance(exc, genai_errors.ClientError) and exc.code == 400:
        return ai_unavailable(
            f"Gemini rejected the request ({exc.status or 'INVALID_ARGUMENT'}). Please try again with a different "
            "photo or message.",
            reason="bad_request",
        )
    if isinstance(exc, (asyncio.TimeoutError, TimeoutError)):
        return ai_unavailable("The AI took too long to answer. Please try again.", reason="timeout")
    if isinstance(exc, httpx.TransportError):
        return ai_unavailable(
            "The server couldn't reach the Gemini API. Check the server's internet connection (or proxy/VPN).",
            reason="network",
        )
    return ai_unavailable(reason="unavailable")


def describe(exc: BaseException) -> str:
    """Short, key-free label for logs."""
    if isinstance(exc, genai_errors.APIError):
        return f"{type(exc).__name__} {exc.code} {exc.status or ''}".strip()
    return type(exc).__name__


# --- diagnostics used by scripts/smoke_gemini.py (re-exported from gemini_client) ---


def is_auth_error(exc: BaseException) -> bool:
    return isinstance(exc, genai_errors.ClientError) and exc.code in (400, 401, 403)


def is_network_error(exc: BaseException) -> bool:
    """The request never reached Google (offline, DNS, proxy, firewall) or got no answer in time."""
    return isinstance(exc, (httpx.TransportError, asyncio.TimeoutError, TimeoutError))


def is_not_found(exc: BaseException) -> bool:
    return isinstance(exc, genai_errors.ClientError) and exc.code == 404


def describe_error(exc: BaseException) -> str:
    """Longer, key-free error description (code, status and a short message)."""
    if isinstance(exc, genai_errors.APIError):
        msg = (exc.message or "").replace("\n", " ")[:200]
        return f"{exc.code} {exc.status or ''}: {msg}".strip()
    return f"{type(exc).__name__}: {str(exc)[:200]}"
