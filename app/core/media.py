"""Signed, expiring URLs for uploaded photos, so /media isn't a public bucket.

A URL carries `exp` (unix seconds) and `sig` = HMAC-SHA256(media key, "<rel_path>:<exp>"), where the media key is
derived from JWT_SECRET for this purpose only, so a photo-link signature is never a value signed with the key
that signs access tokens. The media route
serves the file only when the signature matches and exp is in the future. Links are generated server-side for
the owner when scan/chat data is returned, and they stop working after MEDIA_URL_TTL_S."""

from __future__ import annotations

import hashlib
import hmac
import time

_MEDIA_KEY_LABEL = b"nutriscan/media-url/v1"


def media_key(secret: str) -> bytes:
    """Purpose-specific subkey: HMAC-SHA256(secret, label). Changing the label invalidates all photo links."""
    return hmac.new(secret.encode(), _MEDIA_KEY_LABEL, hashlib.sha256).digest()


def _sig(rel_path: str, exp: int, secret: str) -> str:
    msg = f"{rel_path}:{exp}".encode()
    return hmac.new(media_key(secret), msg, hashlib.sha256).hexdigest()


def sign(rel_path: str, secret: str, ttl_s: int) -> tuple[int, str]:
    exp = int(time.time()) + ttl_s
    return exp, _sig(rel_path, exp, secret)


def verify(rel_path: str, exp: int, sig: str, secret: str) -> bool:
    if exp < int(time.time()):
        return False
    return hmac.compare_digest(sig, _sig(rel_path, exp, secret))
