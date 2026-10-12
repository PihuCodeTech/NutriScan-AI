"""Settings: .env and relative paths resolve against the project folder; pasted keys are cleaned up."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core import config
from app.core.config import ENV_FILE, PROJECT_ROOT, Settings, shell_overrides
from app.services.classifier import HFClassifier


def test_env_file_is_the_project_root_env():
    assert ENV_FILE == PROJECT_ROOT / ".env"
    assert (PROJECT_ROOT / "app" / "main.py").is_file()


def test_relative_paths_resolve_under_project_root(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)  # starting the server from another folder must not change anything
    s = Settings(
        DATABASE_URL="sqlite+aiosqlite:///./nutriscan.db", STORAGE_DIR="./storage/uploads", FRONTEND_DIR="frontend"
    )
    db_url = s.DATABASE_URL
    assert db_url == f"sqlite+aiosqlite:///{PROJECT_ROOT / 'nutriscan.db'}"
    assert Path(s.STORAGE_DIR) == PROJECT_ROOT / "storage" / "uploads"
    assert Path(s.FRONTEND_DIR) == PROJECT_ROOT / "frontend"


@pytest.mark.parametrize(
    "url",
    [
        "sqlite+aiosqlite:////tmp/abs.db",
        "sqlite+aiosqlite:///:memory:",
        "postgresql+asyncpg://user:pw@db:5432/nutriscan",
    ],
)
def test_other_database_urls_are_untouched(url):
    resolved = Settings(DATABASE_URL=url).DATABASE_URL
    assert resolved == url


@pytest.mark.parametrize("raw", ["  AQ.abc123  ", '"AQ.abc123"', "'AQ.abc123'"])
def test_pasted_key_is_trimmed(raw):
    assert Settings(GEMINI_API_KEY=raw).GEMINI_API_KEY == "AQ.abc123"


def test_shell_override_is_detected(monkeypatch, tmp_path):
    env = tmp_path / ".env"
    env.write_text("GEMINI_API_KEY=from-file\nMOCK_AI=false\n")
    monkeypatch.setattr(config, "ENV_FILE", env)
    monkeypatch.setenv("GEMINI_API_KEY", "old-exported-key")
    monkeypatch.setenv("MOCK_AI", "false")
    assert shell_overrides() == ["GEMINI_API_KEY"]


def test_no_env_file_means_no_override_warning(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "ENV_FILE", tmp_path / "missing.env")
    assert shell_overrides() == []


async def test_classifier_reports_loading_while_it_loads(monkeypatch):
    clf = HFClassifier("nateraw/food", 3)
    seen: list[str] = []
    monkeypatch.setattr(clf, "_load_sync", lambda: (seen.append(clf.status), setattr(clf, "_pipe", object())))
    await clf.load()
    assert seen == ["loading"] and clf.status == "loaded"
