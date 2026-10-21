"""Application settings, loaded from environment variables and `.env`."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

from dotenv import dotenv_values
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

APP_VERSION = "1.0.0"
DISCLAIMER = "Estimates only — not medical advice."

# The project folder (the one holding `.env`, `app/`, `frontend/`). `.env` and relative paths are resolved
# against it, so the server finds its key, database and frontend whatever directory it is started from.
PROJECT_ROOT = Path(__file__).resolve().parents[2]
ENV_FILE = PROJECT_ROOT / ".env"

# Settings worth warning about when a value exported in the shell silently overrides `.env`.
_WATCHED_ENV = ("GEMINI_API_KEY", "GEMINI_USE_VERTEX", "GEMINI_MODEL", "GEMINI_FALLBACK_MODEL", "MOCK_AI")


def _under_root(value: str) -> str:
    path = Path(value).expanduser()
    return str(path if path.is_absolute() else (PROJECT_ROOT / path).resolve())


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ENV_FILE, env_file_encoding="utf-8", extra="ignore")

    # App
    APP_ENV: Literal["dev", "test", "prod"] = "dev"
    LOG_LEVEL: str = "INFO"
    PUBLIC_BASE_URL: str = "http://localhost:8000"
    CORS_ORIGINS: str = "*"

    # Database
    DATABASE_URL: str = "sqlite+aiosqlite:///./nutriscan.db"

    # Auth
    JWT_SECRET: str = "dev-insecure-secret-change-me"
    JWT_EXPIRE_MINUTES: int = 10080

    # Gemini
    GEMINI_API_KEY: str = ""
    GEMINI_USE_VERTEX: bool = False
    GEMINI_MODEL: str = "gemini-3.8-flash"
    GEMINI_FALLBACK_MODEL: str = "gemini-3.5-flash-lite"
    GEMINI_TIMEOUT_S: float = 30.0
    # After a model is overloaded / times out, send requests to the other model first for this long (seconds),
    # instead of making every request wait on the struggling one. 0 = off.
    GEMINI_COOLDOWN_S: float = 120.0
    # Gemini 3 "thinking" depth: minimal | low | medium | high, or empty for the model default.
    # Low keeps scans and chat quick; models that don't support the setting simply ignore it here.
    GEMINI_THINKING_LEVEL: str = "low"

    # Mock mode
    MOCK_AI: bool = False

    # Classifier
    CLASSIFIER_ENABLED: bool = True
    CLASSIFIER_MODEL_ID: str = "nateraw/food"
    CLASSIFIER_TOP_K: int = 3

    # Uploads
    MAX_UPLOAD_MB: float = 8
    STORAGE_DIR: str = "./storage/uploads"
    MEDIA_URL_TTL_S: int = 86400  # how long a signed photo URL stays valid (seconds)
    GUEST_RETENTION_DAYS: int = 3  # throw-away guest accounts older than this are cleaned up

    # Web frontend served at /app (skipped if the folder doesn't exist)
    FRONTEND_DIR: str = "./frontend"

    # Limits
    RATE_LIMIT_AI: str = "20/minute"
    # Per client IP (not per token, so rotating guest tokens doesn't help): slows password guessing and
    # stops mass sign-ups that would sidestep the per-user AI limit.
    RATE_LIMIT_LOGIN: str = "10/minute"
    RATE_LIMIT_REGISTER: str = "20/hour"
    CHAT_HISTORY_TURNS: int = 20
    CHAT_MAX_TOOL_ROUNDS: int = 4

    # Monitoring (see app/services/monitoring.py and README "Monitoring")
    # Bearer token for GET /metrics (Prometheus format). Empty = the endpoint is disabled (404).
    METRICS_TOKEN: str = ""
    # Slack / Discord incoming-webhook URL for alerts. Empty = alerts are only logged (level ERROR).
    ALERT_WEBHOOK_URL: str = ""
    ALERT_REPEAT_MIN: int = 240  # re-send a still-firing alert this often (0 = only once)
    MONITOR_INTERVAL_S: float = 60.0  # how often the watchdog checks the database and evaluates alert rules
    GUEST_CLEANUP_INTERVAL_H: float = 24.0  # guest cleanup runs at startup and then this often

    @field_validator("PUBLIC_BASE_URL")
    @classmethod
    def _strip_slash(cls, v: str) -> str:
        return v.rstrip("/")

    @field_validator("GEMINI_API_KEY")
    @classmethod
    def _clean_key(cls, v: str) -> str:
        # Pasted keys often carry stray spaces or quotes, which Google rejects as an invalid key.
        return v.strip().strip("'\"").strip()

    @field_validator("GEMINI_THINKING_LEVEL")
    @classmethod
    def _thinking_level(cls, v: str) -> str:
        v = (v or "").strip().lower()
        if v not in {"", "minimal", "low", "medium", "high"}:
            raise ValueError("GEMINI_THINKING_LEVEL must be minimal, low, medium, high or empty")
        return v

    @field_validator("STORAGE_DIR", "FRONTEND_DIR")
    @classmethod
    def _resolve_dir(cls, v: str) -> str:
        return _under_root(v) if v else v

    @field_validator("DATABASE_URL")
    @classmethod
    def _resolve_sqlite_path(cls, v: str) -> str:
        """`sqlite+aiosqlite:///./nutriscan.db` → absolute path under the project folder.
        Plain `postgres://` / `postgresql://` (as Supabase shows them) → `postgresql+asyncpg://`."""
        if v.startswith(("http://", "https://")):
            raise ValueError(
                "DATABASE_URL must be a database connection string, not an HTTP URL. For Supabase use "
                "Project Settings → Database → Connection string (URI), e.g. "
                "postgresql+asyncpg://postgres.<ref>:<password>@<host>.pooler.supabase.com:6543/postgres"
            )
        for plain in ("postgres://", "postgresql://"):
            if v.startswith(plain):
                return "postgresql+asyncpg://" + v[len(plain):]
        prefix, sep, path = v.partition(":///")
        if not sep or not prefix.startswith("sqlite") or not path or path.startswith(":memory:"):
            return v
        return v if Path(path).is_absolute() else f"{prefix}:///{_under_root(path)}"

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()] or ["*"]

    @property
    def max_upload_bytes(self) -> int:
        return int(self.MAX_UPLOAD_MB * 1024 * 1024)

    @property
    def gemini_status(self) -> str:
        if self.MOCK_AI:
            return "mock"
        return "configured" if self.GEMINI_API_KEY else "missing"


def shell_overrides() -> list[str]:
    """Names of watched settings whose shell environment value differs from (and overrides) `.env`."""
    if not ENV_FILE.is_file():
        return []
    file_values = dotenv_values(ENV_FILE)
    return [
        name
        for name in _WATCHED_ENV
        if name in os.environ and name in file_values and os.environ[name] != (file_values[name] or "")
    ]


_PLACEHOLDER_SECRETS = {"dev-insecure-secret-change-me", "change-me-to-a-long-random-string", ""}
MIN_PROD_SECRET_CHARS = 32


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide settings instance."""
    settings = Settings()
    # JWT_SECRET signs both access tokens and photo URLs: a guessable one lets anyone forge a login.
    if settings.APP_ENV == "prod" and (
        settings.JWT_SECRET in _PLACEHOLDER_SECRETS or len(settings.JWT_SECRET) < MIN_PROD_SECRET_CHARS
    ):
        raise RuntimeError(
            f"JWT_SECRET must be a random value of at least {MIN_PROD_SECRET_CHARS} characters when APP_ENV=prod "
            '(e.g. python -c "import secrets; print(secrets.token_urlsafe(48))")'
        )
    if settings.APP_ENV == "prod" and settings.MOCK_AI:
        raise RuntimeError("MOCK_AI=true serves canned fixtures instead of real analysis; it is not allowed in prod")
    return settings


def production_warnings(settings: Settings) -> list[str]:
    """Misconfigurations that don't stop a prod start but should be fixed (logged as warnings at startup)."""
    if settings.APP_ENV != "prod":
        return []
    warnings = []
    if "*" in settings.cors_origins_list:
        warnings.append(
            "CORS_ORIGINS allows every origin in prod; set it to the frontend's origin(s), "
            "e.g. CORS_ORIGINS=https://app.example.com"
        )
    if not settings.PUBLIC_BASE_URL.startswith("https://") or "localhost" in settings.PUBLIC_BASE_URL:
        warnings.append(
            "PUBLIC_BASE_URL is not a public https:// URL; photo links will be broken or blocked as mixed content"
        )
    if not settings.GEMINI_API_KEY:
        warnings.append("GEMINI_API_KEY is empty; every AI endpoint will return 503 AI_UNAVAILABLE")
    if settings.DATABASE_URL.startswith("sqlite"):
        warnings.append("DATABASE_URL is SQLite in prod; use PostgreSQL (data lives on one container's disk)")
    return warnings
