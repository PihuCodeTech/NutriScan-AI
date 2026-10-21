"""Password hashing (bcrypt) and JWT access tokens."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import bcrypt
import jwt

from app.core.config import get_settings

_ALGORITHM = "HS256"


def _pw_bytes(password: str) -> bytes:
    # bcrypt only uses the first 72 bytes; truncate explicitly (bcrypt>=4.1 raises otherwise).
    return password.encode("utf-8")[:72]


def hash_password(password: str) -> str:
    """Hash a password with bcrypt."""
    return bcrypt.hashpw(_pw_bytes(password), bcrypt.gensalt()).decode("ascii")


def verify_password(password: str, password_hash: str) -> bool:
    """Check a password against its bcrypt hash."""
    try:
        return bcrypt.checkpw(_pw_bytes(password), password_hash.encode("ascii"))
    except ValueError:
        return False


def create_access_token(user_id: str) -> str:
    """Create a signed JWT whose subject is the user id."""
    settings = get_settings()
    now = datetime.now(UTC)
    payload = {"sub": user_id, "iat": now, "exp": now + timedelta(minutes=settings.JWT_EXPIRE_MINUTES)}
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=_ALGORITHM)


def decode_access_token(token: str) -> str | None:
    """Return the user id from a valid token, or None if invalid/expired."""
    try:
        payload = jwt.decode(
            token, get_settings().JWT_SECRET, algorithms=[_ALGORITHM], options={"require": ["exp", "sub"]}
        )
    except jwt.PyJWTError:
        return None
    sub = payload.get("sub")
    return sub if isinstance(sub, str) else None
