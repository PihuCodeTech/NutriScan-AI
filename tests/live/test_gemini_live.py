"""Optional live test against the real Gemini API. Skipped unless GEMINI_API_KEY is set and RUN_LIVE=1.

Note: tests/conftest.py blanks GEMINI_API_KEY for the app, so the key is read from .env directly here.
"""

from __future__ import annotations

import os

import pytest
from dotenv import dotenv_values

from app.core.config import Settings
from app.services.llm.gemini_client import GeminiClient

_KEY = os.environ.get("LIVE_GEMINI_API_KEY") or dotenv_values(".env").get("GEMINI_API_KEY") or ""

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(not (_KEY and os.environ.get("RUN_LIVE") == "1"), reason="needs GEMINI_API_KEY and RUN_LIVE=1"),
]


async def test_live_text_estimate():
    env = dotenv_values(".env")
    settings = Settings(
        GEMINI_API_KEY=_KEY,
        GEMINI_USE_VERTEX=str(env.get("GEMINI_USE_VERTEX", "false")).lower() == "true",
        GEMINI_MODEL=env.get("GEMINI_MODEL") or "gemini-3.8-flash",
        GEMINI_FALLBACK_MODEL=env.get("GEMINI_FALLBACK_MODEL") or "gemini-3.5-flash-lite",
        MOCK_AI=False,
    )
    result = await GeminiClient(settings).estimate_from_text("2 roti and a katori of dal", user_ctx="Country: IN")
    assert result.is_food and result.items
