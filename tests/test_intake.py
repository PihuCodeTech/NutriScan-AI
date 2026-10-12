from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from app.services.nutrition import NUTRIENT_KEYS

IST = ZoneInfo("Asia/Kolkata")

BANANA = {
    "calories": 107,
    "protein_g": 1.3,
    "carbohydrates_g": 27.4,
    "fat_g": 0.4,
    "saturated_fat_g": 0.1,
    "fiber_g": 3.1,
    "sugar_g": 14.7,
    "sodium_mg": 1,
}


def _today():
    return datetime.now(IST).date()


async def _manual(client, headers, *, name="Snack", meal_type="snack", eaten_at=None, items=None):
    body = {
        "name": name,
        "meal_type": meal_type,
        "items": items or [{"name": "Banana", "quantity_g": 120, "nutrients": BANANA}],
    }
    if eaten_at:
        body["eaten_at"] = eaten_at
    r = await client.post("/api/v1/intake", headers=headers, json=body)
    assert r.status_code == 201, r.text
    return r.json()["data"]


async def test_describe_preview(client, auth_headers, mock_llm):
    r = await client.post(
        "/api/v1/intake/describe",
        headers=auth_headers,
        json={"text": "2 roti, dal and a glass of lassi", "meal_type": "dinner"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["code"] == "DESCRIPTION_ANALYSED"
    data = body["data"]
    assert [i["name"] for i in data["items"]] == ["Roti", "Dal", "Lassi"]
    assert all(i["id"] for i in data["items"])
    for key in NUTRIENT_KEYS:
        assert data["totals"][key] == pytest.approx(sum(i["nutrients"][key] for i in data["items"]), abs=0.15)
    assert 0 <= data["health"]["score"] <= 100
    assert data["intake_entry"] is None
    assert (await client.get("/api/v1/intake/daily", headers=auth_headers)).json()["data"]["entries"] == []


async def test_describe_with_log_creates_entry(client, auth_headers):
    r = await client.post(
        "/api/v1/intake/describe",
        headers=auth_headers,
        json={"text": "poha and chai", "meal_type": "breakfast", "log": True},
    )
    data = r.json()["data"]
    entry = data["intake_entry"]
    assert entry["source"] == "description" and entry["meal_type"] == "breakfast"
    assert entry["totals"] == data["totals"]
    daily = (await client.get("/api/v1/intake/daily", headers=auth_headers)).json()["data"]
    assert [e["id"] for e in daily["entries"]] == [entry["id"]]


async def test_describe_not_food(client, auth_headers):
    r = await client.post("/api/v1/intake/describe", headers=auth_headers, json={"text": "this is not food"})
    assert r.status_code == 422 and r.json()["code"] == "NOT_FOOD"


async def test_manual_entry(client, auth_headers):
    entry = await _manual(client, auth_headers, name="Evening snack")
    assert entry["source"] == "manual"
    assert entry["name"] == "Evening snack"
    assert entry["totals"]["calories"] == 107
    assert entry["items"][0]["source"] == "user_added"
    r = await client.post(
        "/api/v1/intake",
        headers=auth_headers,
        json={
            "name": "x",
            "meal_type": "snack",
            "items": [{"name": "y", "quantity_g": 10, "nutrients": {"calories": -1}}],
        },
    )
    assert r.status_code == 422


async def test_daily_totals_equal_sum_of_entries(client, auth_headers):
    a = await _manual(client, auth_headers, name="A")
    b = await _manual(
        client,
        auth_headers,
        name="B",
        meal_type="lunch",
        items=[
            {"name": "Banana", "quantity_g": 120, "nutrients": BANANA},
            {"name": "Egg", "quantity_g": 50, "nutrients": {**BANANA, "calories": 72, "protein_g": 6.3}},
        ],
    )
    r = await client.get("/api/v1/intake/daily", headers=auth_headers)
    data = r.json()["data"]
    assert data["date"] == _today().isoformat()
    assert {e["id"] for e in data["entries"]} == {a["id"], b["id"]}
    for key in NUTRIENT_KEYS:
        assert data["totals"][key] == pytest.approx(a["totals"][key] + b["totals"][key], abs=0.15)
    assert data["targets"]["calories"] == 2000
    assert data["remaining"]["calories"] == 2000 - data["totals"]["calories"]
    assert data["percent_of_target"]["calories"] == round(100 * data["totals"]["calories"] / 2000)
    assert data["health_status"] in {"on_track", "under"}
    assert isinstance(data["status_flags"], list)


async def test_daily_uses_profile_timezone(client, auth_headers):
    # 23:30 UTC on day D is already day D+1 in IST (UTC+5:30)
    eaten = datetime.now(UTC).replace(hour=23, minute=30, second=0, microsecond=0) - timedelta(days=2)
    await _manual(client, auth_headers, eaten_at=eaten.isoformat())
    ist_day = eaten.astimezone(IST).date()
    assert ist_day == eaten.date() + timedelta(days=1)
    data = (await client.get(f"/api/v1/intake/daily?date={ist_day}", headers=auth_headers)).json()["data"]
    assert len(data["entries"]) == 1
    assert data["health_status"] == "under"  # past day, well under target
    utc_day = (await client.get(f"/api/v1/intake/daily?date={eaten.date()}", headers=auth_headers)).json()["data"]
    assert utc_day["entries"] == [] and utc_day["health_status"] == "no_data"

    # switching the profile timezone to UTC changes the bucket for new entries
    await client.put("/api/v1/users/me/profile", headers=auth_headers, json={"timezone": "UTC"})
    await _manual(client, auth_headers, eaten_at=eaten.isoformat())
    utc_day = (await client.get(f"/api/v1/intake/daily?date={eaten.date()}", headers=auth_headers)).json()["data"]
    assert len(utc_day["entries"]) == 1


async def test_summary_zero_fills_and_streak(client, auth_headers):
    now = datetime.now(UTC)
    for days_ago in (0, 1, 3):
        await _manual(client, auth_headers, eaten_at=(now - timedelta(days=days_ago)).isoformat())
    r = await client.get("/api/v1/intake/summary?days=7", headers=auth_headers)
    data = r.json()["data"]
    assert len(data["days"]) == 7
    assert data["days"][-1]["date"] == _today().isoformat()
    logged = [d for d in data["days"] if d["entries"]]
    assert len(logged) == 3 and data["days_logged"] == 3
    empty = [d for d in data["days"] if not d["entries"]]
    assert all(d["totals"]["calories"] == 0 and d["calorie_percent"] == 0 for d in empty)
    assert data["streak_days_logged"] == 2
    assert data["averages"]["calories"] == 107
    assert data["top_foods"] == [{"name": "Banana", "count": 3}]
    assert (await client.get("/api/v1/intake/summary?days=0", headers=auth_headers)).status_code == 422
    assert (await client.get("/api/v1/intake/summary?days=32", headers=auth_headers)).status_code == 422


async def test_summary_empty(client, auth_headers):
    data = (await client.get("/api/v1/intake/summary?days=3", headers=auth_headers)).json()["data"]
    assert len(data["days"]) == 3
    assert data["streak_days_logged"] == 0 and data["top_foods"] == [] and data["averages"]["calories"] == 0


async def test_delete_entry_and_ownership(client, auth_headers, second_user_headers):
    entry = await _manual(client, auth_headers)
    assert (await client.delete(f"/api/v1/intake/{entry['id']}", headers=second_user_headers)).status_code == 404
    r = await client.delete(f"/api/v1/intake/{entry['id']}", headers=auth_headers)
    assert r.status_code == 200 and r.json()["code"] == "DELETED"
    assert (await client.delete(f"/api/v1/intake/{entry['id']}", headers=auth_headers)).status_code == 404
    other = (await client.get("/api/v1/intake/daily", headers=second_user_headers)).json()["data"]
    assert other["entries"] == []
