"""Generate example API payloads in mock mode (no key, no network) into docs/examples/*.json.

Gives frontend developers a real payload for every screen. Runs the real app in-process against a temporary
SQLite DB.
"""

from __future__ import annotations

import asyncio
import io
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
_TMP = tempfile.mkdtemp(prefix="nutriscan-examples-")
os.environ.update(
    {
        "APP_ENV": "test",
        "MOCK_AI": "true",
        "GEMINI_API_KEY": "",
        "DATABASE_URL": f"sqlite+aiosqlite:///{_TMP}/examples.db",
        "STORAGE_DIR": f"{_TMP}/uploads",
        "PUBLIC_BASE_URL": "http://localhost:8000",
        "LOG_LEVEL": "WARNING",
    }
)

import httpx  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402

from app.main import create_app  # noqa: E402

OUT = ROOT / "docs" / "examples"


def plate() -> bytes:
    img = Image.new("RGB", (400, 400), (235, 230, 220))
    d = ImageDraw.Draw(img)
    d.ellipse((20, 20, 380, 380), fill=(250, 250, 250))
    d.ellipse((70, 80, 200, 210), fill=(150, 60, 30))
    d.ellipse((190, 120, 330, 260), fill=(245, 240, 225))
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


def save(name: str, payload: object) -> None:
    (OUT / f"{name}.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote docs/examples/{name}.json")


async def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with app.router.lifespan_context(app), httpx.AsyncClient(transport=transport, base_url="http://api") as c:
        reg = await c.post(
            "/api/v1/auth/register", json={"email": "asha@example.com", "password": "password123", "name": "Asha"}
        )
        save("auth_register", reg.json())
        h = {"Authorization": f"Bearer {reg.json()['data']['access_token']}"}
        profile = {
            "age": 20,
            "sex": "female",
            "height_cm": 160,
            "weight_kg": 55,
            "activity_level": "light",
            "goal": "maintain",
            "diet_type": "veg",
            "allergies": ["peanuts"],
        }
        await c.put("/api/v1/users/me/profile", headers=h, json=profile)
        save("users_me", (await c.get("/api/v1/users/me", headers=h)).json())
        save("targets", (await c.get("/api/v1/users/me/targets", headers=h)).json())
        save("meta", (await c.get("/api/v1/meta")).json())

        scan = await c.post(
            "/api/v1/scans",
            headers=h,
            files={"image": ("thali.jpg", plate(), "image/jpeg")},
            data={"description": "hostel lunch", "meal_type": "lunch"},
        )
        save("scan_result", scan.json())
        scan_data = scan.json()["data"]
        not_food = await c.post(
            "/api/v1/scans",
            headers=h,
            files={"image": ("desk.jpg", plate(), "image/jpeg")},
            data={"description": "not food"},
        )
        save("error_not_food", not_food.json())
        edit = await c.patch(
            f"/api/v1/scans/{scan_data['id']}/items",
            headers=h,
            json={
                "items": [{"id": scan_data["items"][0]["id"], "quantity_g": 200}, {"name": "Curd", "quantity_g": 100}]
            },
        )
        save("scan_edited", edit.json())
        save("scans_list", (await c.get("/api/v1/scans?page=1&page_size=20", headers=h)).json())
        save("intake_entry_from_scan", (await c.post(f"/api/v1/scans/{scan_data['id']}/log", headers=h)).json())
        save(
            "intake_describe",
            (
                await c.post(
                    "/api/v1/intake/describe",
                    headers=h,
                    json={"text": "2 roti, dal and a glass of lassi", "meal_type": "dinner", "log": True},
                )
            ).json(),
        )
        save("intake_daily", (await c.get("/api/v1/intake/daily", headers=h)).json())
        save("intake_summary", (await c.get("/api/v1/intake/summary?days=7", headers=h)).json())
        save("insight_daily", (await c.get("/api/v1/insights/daily", headers=h)).json())

        save("chat_suggestions", (await c.get(f"/api/v1/chat/suggestions?scan_id={scan_data['id']}", headers=h)).json())
        session = await c.post("/api/v1/chat/sessions", headers=h, json={"scan_id": scan_data["id"]})
        save("chat_session", session.json())
        sid = session.json()["data"]["id"]
        save(
            "chat_message_exchange",
            (
                await c.post(f"/api/v1/chat/sessions/{sid}/messages", headers=h, data={"text": "How did I do today?"})
            ).json(),
        )
        stream = await c.post(
            f"/api/v1/chat/sessions/{sid}/messages/stream", headers=h, data={"text": "log a banana as snack"}
        )
        (OUT / "chat_stream.txt").write_text(stream.text, encoding="utf-8")
        print("wrote docs/examples/chat_stream.txt")
        save("chat_session_detail", (await c.get(f"/api/v1/chat/sessions/{sid}", headers=h)).json())
        save("error_unauthorized", (await c.get("/api/v1/users/me")).json())
        save("error_validation", (await c.post("/api/v1/intake/describe", headers=h, json={"text": ""})).json())


if __name__ == "__main__":
    asyncio.run(main())
