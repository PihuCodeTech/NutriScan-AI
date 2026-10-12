"""Test setup: MOCK_AI, a fresh SQLite DB + storage dir per test, and auth helpers. No network access."""

from __future__ import annotations

import io
import os
import tempfile
import uuid
from collections.abc import AsyncIterator

_BOOT_DIR = tempfile.mkdtemp(prefix="nutriscan-test-")
os.environ.update(
    {
        "APP_ENV": "test",
        "MOCK_AI": "true",
        "GEMINI_API_KEY": "",
        "GEMINI_USE_VERTEX": "false",
        "DATABASE_URL": f"sqlite+aiosqlite:///{_BOOT_DIR}/boot.db",
        "STORAGE_DIR": f"{_BOOT_DIR}/uploads",
        "PUBLIC_BASE_URL": "http://testserver",
        "RATE_LIMIT_AI": "1000/minute",
        "CLASSIFIER_ENABLED": "true",
        "LOG_LEVEL": "WARNING",
        "JWT_SECRET": "test-secret-not-for-production-0123456789",
        "CHAT_HISTORY_TURNS": "20",
        "CHAT_MAX_TOOL_ROUNDS": "4",
    }
)

import bcrypt  # noqa: E402
import httpx  # noqa: E402
import pytest  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402

from app.core.config import Settings, get_settings  # noqa: E402
from app.core.rate_limit import limiter  # noqa: E402
from app.main import create_app  # noqa: E402
from app.services.llm.mock_client import MockGeminiClient  # noqa: E402

# Fast bcrypt for tests only.
_orig_gensalt = bcrypt.gensalt
bcrypt.gensalt = lambda rounds=4, prefix=b"2b": _orig_gensalt(4, prefix)  # type: ignore[assignment]


@pytest.fixture
def settings(tmp_path, monkeypatch) -> Settings:
    s = get_settings()
    monkeypatch.setattr(s, "DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path}/test.db")
    monkeypatch.setattr(s, "STORAGE_DIR", str(tmp_path / "uploads"))
    return s


@pytest.fixture
async def app(settings: Settings) -> AsyncIterator[FastAPI]:
    application = create_app(settings)
    limiter.reset()
    async with application.router.lifespan_context(application):
        yield application


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield c


@pytest.fixture
def mock_llm(app: FastAPI) -> MockGeminiClient:
    return app.state.llm


async def register_user(client: httpx.AsyncClient, name: str = "Asha") -> dict[str, str]:
    email = f"{name.lower()}-{uuid.uuid4().hex[:8]}@example.com"
    r = await client.post("/api/v1/auth/register", json={"email": email, "password": "password123", "name": name})
    assert r.status_code == 201, r.text
    return {"Authorization": f"Bearer {r.json()['data']['access_token']}"}


@pytest.fixture
async def auth_headers(client: httpx.AsyncClient) -> dict[str, str]:
    return await register_user(client, "Asha")


@pytest.fixture
async def second_user_headers(client: httpx.AsyncClient) -> dict[str, str]:
    return await register_user(client, "Ravi")


def make_jpeg(size: int = 256, fmt: str = "JPEG") -> bytes:
    """A generated plate-like image with some colour blobs."""
    img = Image.new("RGB", (size, size), (235, 230, 220))
    d = ImageDraw.Draw(img)
    d.ellipse((16, 16, size - 16, size - 16), fill=(250, 250, 250), outline=(180, 180, 180))
    d.ellipse((50, 60, 130, 140), fill=(150, 60, 30))  # rajma
    d.ellipse((120, 90, 210, 180), fill=(245, 240, 225))  # rice
    d.rectangle((70, 170, 120, 200), fill=(200, 80, 120))  # onion
    buf = io.BytesIO()
    img.save(buf, format=fmt)
    return buf.getvalue()


@pytest.fixture
def sample_jpeg() -> bytes:
    return make_jpeg()


async def create_scan(client: httpx.AsyncClient, headers: dict[str, str], image: bytes, **form: str) -> httpx.Response:
    return await client.post(
        "/api/v1/scans", headers=headers, files={"image": ("plate.jpg", image, "image/jpeg")}, data=form
    )
