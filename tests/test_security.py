"""Security regression tests: auth abuse limits, JWT rules, upload parsing, body size cap and response headers."""

from __future__ import annotations

import io
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import jwt
import pytest
from PIL import Image, TiffImagePlugin

from app.core.config import Settings, get_settings
from app.core.errors import AppError
from app.services import images, user_service
from tests.conftest import make_jpeg


def _creds() -> dict[str, str]:
    return {"email": f"u-{uuid.uuid4().hex[:8]}@example.com", "password": "password123", "name": "U"}


# ---------------------------------------------------------------------- auth abuse


async def test_login_is_rate_limited_per_ip(client, settings, monkeypatch):
    monkeypatch.setattr(settings, "RATE_LIMIT_LOGIN", "3/minute")
    creds = _creds()
    await client.post("/api/v1/auth/register", json=creds)
    wrong = {"email": creds["email"], "password": "guess-guess"}
    for _ in range(3):
        assert (await client.post("/api/v1/auth/login", json=wrong)).status_code == 401
    r = await client.post("/api/v1/auth/login", json={**wrong, "password": creds["password"]})
    assert r.status_code == 429 and r.json()["code"] == "RATE_LIMITED"


async def test_bearer_token_does_not_buy_a_fresh_login_bucket(client, settings, monkeypatch):
    """Auth limits are keyed by IP only: rotating (guest) tokens must not reset the counter."""
    monkeypatch.setattr(settings, "RATE_LIMIT_LOGIN", "2/minute")
    wrong = {"email": "victim@example.com", "password": "guess-guess"}
    for _ in range(2):
        await client.post("/api/v1/auth/login", json=wrong)
    guest = (await client.post("/api/v1/auth/guest")).json()["data"]["access_token"]
    r = await client.post("/api/v1/auth/login", json=wrong, headers={"Authorization": f"Bearer {guest}"})
    assert r.status_code == 429


async def test_register_is_rate_limited_per_ip(client, settings, monkeypatch):
    monkeypatch.setattr(settings, "RATE_LIMIT_REGISTER", "2/hour")
    for _ in range(2):
        assert (await client.post("/api/v1/auth/register", json=_creds())).status_code == 201
    r = await client.post("/api/v1/auth/register", json=_creds())
    assert r.status_code == 429 and r.json()["code"] == "RATE_LIMITED"


async def test_unknown_email_still_runs_bcrypt(client, monkeypatch):
    """Same work for unknown and known emails, so response time doesn't reveal which accounts exist."""
    calls: list[str] = []
    real = user_service.verify_password
    monkeypatch.setattr(user_service, "verify_password", lambda pw, h: calls.append(h) or real(pw, h))
    r = await client.post("/api/v1/auth/login", json={"email": "nobody@example.com", "password": "whatever1"})
    assert r.status_code == 401 and len(calls) == 1


async def test_tokens_without_expiry_are_rejected(client, auth_headers, settings):
    me = (await client.get("/api/v1/users/me", headers=auth_headers)).json()["data"]
    forever = jwt.encode({"sub": me["id"]}, settings.JWT_SECRET, algorithm="HS256")
    r = await client.get("/api/v1/users/me", headers={"Authorization": f"Bearer {forever}"})
    assert r.status_code == 401
    expired = jwt.encode(
        {"sub": me["id"], "exp": datetime.now(UTC) - timedelta(seconds=5)}, settings.JWT_SECRET, algorithm="HS256"
    )
    assert (await client.get("/api/v1/users/me", headers={"Authorization": f"Bearer {expired}"})).status_code == 401


@pytest.mark.parametrize("secret", ["", "change-me-to-a-long-random-string", "short-but-not-default"])
def test_prod_refuses_weak_jwt_secret(monkeypatch, secret):
    monkeypatch.setenv("APP_ENV", "prod")
    monkeypatch.setenv("JWT_SECRET", secret)
    get_settings.cache_clear()
    try:
        with pytest.raises(RuntimeError, match="JWT_SECRET"):
            get_settings()
    finally:
        get_settings.cache_clear()


def test_prod_accepts_strong_jwt_secret(monkeypatch):
    monkeypatch.setenv("APP_ENV", "prod")
    monkeypatch.setenv("MOCK_AI", "false")
    monkeypatch.setenv("JWT_SECRET", "x" * 48)
    get_settings.cache_clear()
    try:
        assert isinstance(get_settings(), Settings)
    finally:
        get_settings.cache_clear()


def test_prod_refuses_mock_ai(monkeypatch):
    monkeypatch.setenv("APP_ENV", "prod")
    monkeypatch.setenv("MOCK_AI", "true")
    monkeypatch.setenv("JWT_SECRET", "x" * 48)
    get_settings.cache_clear()
    try:
        with pytest.raises(RuntimeError, match="MOCK_AI"):
            get_settings()
    finally:
        get_settings.cache_clear()


def test_production_warnings_flag_each_misconfiguration():
    from app.core.config import production_warnings

    bad = Settings(
        APP_ENV="prod",
        CORS_ORIGINS="*",
        PUBLIC_BASE_URL="http://localhost:8000",
        GEMINI_API_KEY="",
        DATABASE_URL="sqlite+aiosqlite:///./x.db",
        _env_file=None,
    )
    text = " ".join(production_warnings(bad))
    for name in ("CORS_ORIGINS", "PUBLIC_BASE_URL", "GEMINI_API_KEY", "SQLite"):
        assert name in text, name
    good = Settings(
        APP_ENV="prod",
        CORS_ORIGINS="https://app.example.com",
        PUBLIC_BASE_URL="https://api.example.com",
        GEMINI_API_KEY="k",
        DATABASE_URL="postgresql+asyncpg://u:p@db.example.com:5432/x",
        _env_file=None,
    )
    assert production_warnings(good) == []
    assert production_warnings(Settings(APP_ENV="dev", _env_file=None)) == []


# ---------------------------------------------------------------------- upload parsing


def _tiff() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (8, 8), (10, 20, 30)).save(buf, format="TIFF")
    return buf.getvalue()


def test_non_allowed_decoders_never_touch_upload_bytes(monkeypatch):
    """A TIFF (where most recent Pillow CVEs live) must be rejected without the TIFF plugin parsing it."""

    def tripwire(self):  # pragma: no cover - only runs if the TIFF decoder is reached
        raise AssertionError("TIFF decoder was invoked on an upload")

    monkeypatch.setattr(TiffImagePlugin.TiffImageFile, "_open", tripwire)
    with pytest.raises(AppError) as exc:
        images.normalize_image_bytes(_tiff())
    assert exc.value.code == "INVALID_IMAGE"


@pytest.mark.filterwarnings("ignore::PIL.Image.DecompressionBombWarning")
def test_pixel_flood_is_refused_before_decoding():
    big = Image.new("1", (8000, 7000))  # 56 MP: over MAX_PIXELS but under Pillow's own 2x hard limit
    buf = io.BytesIO()
    big.save(buf, format="PNG")
    with pytest.raises(AppError) as exc:
        images.normalize_image_bytes(buf.getvalue())
    assert exc.value.code == "INVALID_IMAGE" and "too large" in exc.value.message


def test_allowed_formats_still_work():
    for fmt in ("JPEG", "PNG", "WEBP"):
        assert images.normalize_image_bytes(make_jpeg(64, fmt=fmt)).mime == "image/jpeg"


# ---------------------------------------------------------------------- request body cap


async def test_oversized_body_is_refused_from_content_length(client, auth_headers, settings, mock_llm):
    cap = settings.max_upload_bytes + 1024 * 1024
    r = await client.post(
        "/api/v1/scans",
        headers={**auth_headers, "Content-Type": "multipart/form-data; boundary=x", "Content-Length": str(cap + 1)},
        content=b"x" * 10,
    )
    assert r.status_code == 413 and r.json()["code"] == "FILE_TOO_LARGE"
    assert mock_llm.calls["analyze_food_image"] == 0


async def test_oversized_chunked_body_is_cut_off_while_streaming(client, auth_headers, settings, mock_llm):
    cap = settings.max_upload_bytes + 1024 * 1024
    sent = 0

    async def body():
        nonlocal sent
        chunk = b"y" * (1024 * 1024)
        while sent <= cap + len(chunk):
            sent += len(chunk)
            yield chunk

    r = await client.post(
        "/api/v1/intake/describe",
        headers={**auth_headers, "Content-Type": "application/json"},
        content=body(),
    )
    assert r.status_code == 413 and r.json()["code"] == "FILE_TOO_LARGE"
    assert mock_llm.calls["estimate_from_text"] == 0
    assert not list(Path(settings.STORAGE_DIR).rglob("*.jpg"))


async def test_normal_upload_passes_the_cap(client, auth_headers, sample_jpeg):
    r = await client.post("/api/v1/scans", headers=auth_headers, files={"image": ("p.jpg", sample_jpeg, "image/jpeg")})
    assert r.status_code == 201


# ---------------------------------------------------------------------- headers


async def test_security_headers_on_api_responses(client):
    r = await client.get("/api/v1/health")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"
    assert r.headers["referrer-policy"] == "no-referrer"
    assert "content-security-policy" not in r.headers  # Swagger UI (/docs) needs its CDN scripts
    r = await client.get("/api/v1/nope")
    assert r.status_code == 404 and r.headers["x-content-type-options"] == "nosniff"


async def test_web_app_gets_a_strict_csp(client):
    r = await client.get("/app/")
    assert r.status_code == 200
    csp = r.headers["content-security-policy"]
    assert "default-src 'self'" in csp and "frame-ancestors 'none'" in csp and "object-src 'none'" in csp
    assert "'unsafe-inline'" not in csp.split("script-src", 1)[1].split(";", 1)[0]  # no inline scripts


async def test_csp_hash_matches_the_only_inline_handler(client):
    """If index.html's inline handlers change, the CSP hash must change with them (or the fonts won't load)."""
    import base64
    import hashlib
    import re

    html = (await client.get("/app/")).text
    handlers = re.findall(r'\son[a-z]+="([^"]*)"', html)
    assert "<script>" not in html and "<script " not in html.replace('<script src="', "")
    csp = (await client.get("/app/")).headers["content-security-policy"]
    for code in handlers:
        digest = base64.b64encode(hashlib.sha256(code.encode()).digest()).decode()
        assert f"'sha256-{digest}'" in csp, code


# ---------------------------------------------------------------------- key separation and prod config


def test_photo_links_use_a_key_derived_from_but_distinct_from_jwt_secret(settings):
    import hashlib
    import hmac

    from app.core import media

    exp, sig = media.sign("2026/10/x.jpg", settings.JWT_SECRET, 60)
    raw = hmac.new(settings.JWT_SECRET.encode(), f"2026/10/x.jpg:{exp}".encode(), hashlib.sha256).hexdigest()
    assert sig != raw  # not signed with the token key itself
    assert media.media_key(settings.JWT_SECRET) != settings.JWT_SECRET.encode()
    assert media.verify("2026/10/x.jpg", exp, sig, settings.JWT_SECRET)
    assert not media.verify("2026/10/x.jpg", exp, raw, settings.JWT_SECRET)  # old-style links stop working


def test_prod_warns_about_wildcard_cors(settings, monkeypatch, caplog):
    from app import main
    from app.main import create_app

    monkeypatch.setattr(main, "configure_logging", lambda level: None)  # it would replace caplog's handler
    monkeypatch.setattr(settings, "APP_ENV", "prod")
    monkeypatch.setattr(settings, "CORS_ORIGINS", "*")
    with caplog.at_level("WARNING", logger="app"):
        create_app(settings)
    assert any("CORS_ORIGINS allows every origin" in r.getMessage() for r in caplog.records)

    caplog.clear()
    monkeypatch.setattr(settings, "CORS_ORIGINS", "https://app.example.com")
    with caplog.at_level("WARNING", logger="app"):
        create_app(settings)
    assert not any("CORS_ORIGINS" in r.getMessage() for r in caplog.records)
