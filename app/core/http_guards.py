"""Transport-level guards: a request body size cap and security response headers (pure ASGI middleware)."""

from __future__ import annotations

from starlette.exceptions import HTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.responses import fail

# Room for multipart boundaries and the small text fields sent next to a photo.
BODY_OVERHEAD_BYTES = 1024 * 1024

_TOO_LARGE = "Request body is too large."

# The web app: own scripts only (plus the hashed `onload` that swaps the font stylesheet in), Google Fonts,
# inline style attributes, and blob:/data: images for photo previews. No framing, no plugins, no <base>.
FRONTEND_CSP = "; ".join(
    [
        "default-src 'self'",
        "script-src 'self' 'unsafe-hashes' 'sha256-MhtPZXr7+LpJUY5qtMutB+qWfQtMaPccfe7QXtCcEYc='",
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
        "font-src 'self' https://fonts.gstatic.com",
        "img-src 'self' blob: data:",
        "connect-src 'self'",
        "object-src 'none'",
        "base-uri 'none'",
        "form-action 'self'",
        "frame-ancestors 'none'",
    ]
)

_BASE_HEADERS = [
    (b"x-content-type-options", b"nosniff"),
    (b"x-frame-options", b"DENY"),
    (b"referrer-policy", b"no-referrer"),  # keeps signed photo URLs and tokens out of Referer headers
    (b"cross-origin-opener-policy", b"same-origin"),
]


class BodySizeLimitMiddleware:
    """Reject request bodies over `max_bytes` before they are buffered or spooled to disk.

    A declared Content-Length over the cap gets an immediate 413; a chunked body is counted as it streams and
    the request fails with 413 once it passes the cap."""

    def __init__(self, app: ASGIApp, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        declared = dict(scope.get("headers") or []).get(b"content-length")
        if declared is not None:
            try:
                too_large = int(declared) > self.max_bytes
            except ValueError:
                too_large = False  # the server rejects a malformed Content-Length itself
            if too_large:
                await fail("FILE_TOO_LARGE", _TOO_LARGE, 413)(scope, receive, send)
                return

        received = 0

        async def limited_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    raise HTTPException(413, _TOO_LARGE)  # rendered as the FILE_TOO_LARGE envelope
            return message

        await self.app(scope, limited_receive, send)


class SecurityHeadersMiddleware:
    """Add nosniff / framing / referrer headers to every response, and a CSP to the web app under `/app`."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path = scope.get("path", "")
        is_frontend = path == "/app" or path.startswith("/app/")

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                present = {k.lower() for k, _ in headers}
                headers += [(k, v) for k, v in _BASE_HEADERS if k not in present]
                if is_frontend and b"content-security-policy" not in present:
                    headers.append((b"content-security-policy", FRONTEND_CSP.encode()))
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_wrapper)
