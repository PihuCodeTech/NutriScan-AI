"""Export the OpenAPI schema to docs/openapi.json (no server, no AI calls, no model download)."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("MOCK_AI", "true")

from app.main import create_app  # noqa: E402


def main() -> None:
    spec = create_app().openapi()
    out = ROOT / "docs" / "openapi.json"
    out.write_text(json.dumps(spec, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {out.relative_to(ROOT)} ({len(spec['paths'])} paths)")


if __name__ == "__main__":
    main()
