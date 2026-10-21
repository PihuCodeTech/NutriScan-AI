"""QA: intake timezone rules, chat permissions and edge cases, insights, and database/AI failure handling."""

from __future__ import annotations

from datetime import date, timedelta

import httpx
import pytest
from sqlalchemy.exc import OperationalError

from app.core.errors import AppError
from app.db.session import get_db
from app.services import intake_service
from app.services.llm.schemas import ChatTurn, FunctionCall
from tests.conftest import create_scan, make_jpeg, register_user

NUTRIENTS = {"calories": 300, "protein_g": 10, "carbohydrates_g": 40, "fat_g": 10}


def _manual(eaten_at: str | None = None, **extra) -> dict:
    body = {
        "name": "Meal",
        "meal_type": "dinner",
        "items": [{"name": "Thali", "quantity_g": 300, "nutrients": NUTRIENTS}],
    }
    if eaten_at:
        body["eaten_at"] = eaten_at
    return {**body, **extra}


# ---------------------------------------------------------------------- intake


async def test_eaten_at_lands_on_the_users_local_day(client, auth_headers):
    # 01:00 IST on the 21st is 19:30 UTC on the 20th: it belongs to the 21st for an Asia/Kolkata user
    r = await client.post("/api/v1/intake", headers=auth_headers, json=_manual("2026-10-21T01:00:00+05:30"))
    assert r.status_code == 201
    # A naive timestamp is UTC: 20:00 UTC on the 20th is 01:30 IST on the 21st
    await client.post("/api/v1/intake", headers=auth_headers, json=_manual("2026-10-20T20:00:00"))
    day21 = (await client.get("/api/v1/intake/daily?date=2026-10-21", headers=auth_headers)).json()["data"]
    day20 = (await client.get("/api/v1/intake/daily?date=2026-10-20", headers=auth_headers)).json()["data"]
    assert len(day21["entries"]) == 2 and day20["entries"] == []
    assert day21["totals"]["calories"] == 600
    assert day20["health_status"] == "no_data" and day20["status_flags"] == []


async def test_changing_timezone_moves_new_entries_to_the_new_local_day(client, auth_headers):
    await client.put("/api/v1/users/me/profile", headers=auth_headers, json={"timezone": "America/New_York"})
    # 02:00 UTC on the 21st is 22:00 on the 20th in New York (EDT)
    await client.post("/api/v1/intake", headers=auth_headers, json=_manual("2026-10-21T02:00:00Z"))
    day20 = (await client.get("/api/v1/intake/daily?date=2026-10-20", headers=auth_headers)).json()["data"]
    assert len(day20["entries"]) == 1


@pytest.mark.parametrize(
    "body",
    [
        _manual(items=[]),
        _manual(items=[{"name": "x", "nutrients": {"calories": -5}}]),
        _manual(items=[{"name": "", "nutrients": {}}]),
        _manual(items=[{"name": "x", "quantity_g": 0, "nutrients": {}}]),
        _manual(items=[{"name": "x", "quantity_g": 5001, "nutrients": {}}]),
        _manual(items=[{"name": "x", "nutrients": {}}] * 31),
        _manual(meal_type="brunch"),
        _manual(eaten_at="yesterday"),
        {"meal_type": "lunch", "items": [{"name": "x", "nutrients": {}}]},  # no name
    ],
)
async def test_manual_intake_validation(client, auth_headers, body):
    r = await client.post("/api/v1/intake", headers=auth_headers, json=body)
    assert r.status_code == 422 and r.json()["code"] == "VALIDATION_ERROR"
    assert r.json()["details"]  # field-level errors for the frontend


async def test_manual_totals_are_computed_server_side_not_trusted(client, auth_headers):
    body = _manual()
    body["totals"] = {"calories": 1}  # ignored: totals are always summed by the backend
    body["items"].append({"name": "Chai", "nutrients": {"calories": 90.44, "sodium_mg": 20.6}})
    r = await client.post("/api/v1/intake", headers=auth_headers, json=body)
    assert r.json()["data"]["totals"]["calories"] == 390
    assert r.json()["data"]["totals"]["sodium_mg"] == 21


async def test_future_eaten_at_is_rejected(client, auth_headers):
    r = await client.post("/api/v1/intake", headers=auth_headers, json=_manual("2030-01-01T12:00:00Z"))
    assert r.status_code == 422 and r.json()["details"][0]["loc"] == ["body", "eaten_at"]
    r = await client.post("/api/v1/intake", headers=auth_headers, json=_manual("2020-01-01T12:00:00Z"))
    assert r.status_code == 422
    assert (await client.get("/api/v1/intake", headers=auth_headers)).json()["data"]["total"] == 0


async def test_future_eaten_at_is_rejected_when_logging_a_scan(client, auth_headers, sample_jpeg):
    scan = (await create_scan(client, auth_headers, sample_jpeg)).json()["data"]
    r = await client.post(
        f"/api/v1/scans/{scan['id']}/log", headers=auth_headers, json={"eaten_at": "2030-01-01T12:00:00Z"}
    )
    assert r.status_code == 422
    assert (await client.get(f"/api/v1/scans/{scan['id']}", headers=auth_headers)).json()["data"][
        "logged_intake_id"
    ] is None


@pytest.mark.parametrize(
    "url",
    [
        "/api/v1/intake/summary?days=0",
        "/api/v1/intake/summary?days=32",
        "/api/v1/intake?days=91",
        "/api/v1/intake?page=0",
    ],
)
async def test_intake_query_bounds(client, auth_headers, url):
    assert (await client.get(url, headers=auth_headers)).status_code == 422


async def test_new_user_empty_states(client, auth_headers):
    daily = (await client.get("/api/v1/intake/daily", headers=auth_headers)).json()["data"]
    assert daily["entries"] == [] and daily["health_status"] == "no_data"
    assert daily["remaining"]["calories"] == daily["targets"]["calories"]
    summary = (await client.get("/api/v1/intake/summary?days=1", headers=auth_headers)).json()["data"]
    assert summary["days_logged"] == 0 and summary["streak_days_logged"] == 0 and summary["top_foods"] == []
    assert all(v == 0 for v in summary["averages"].values())
    assert (await client.get("/api/v1/intake", headers=auth_headers)).json()["data"]["items"] == []
    assert (await client.get("/api/v1/scans", headers=auth_headers)).json()["data"]["items"] == []
    assert (await client.get("/api/v1/chat/sessions", headers=auth_headers)).json()["data"]["items"] == []


async def test_clearing_profile_fields_falls_back_to_default_targets(client, auth_headers):
    full = {"age": 20, "sex": "female", "height_cm": 160, "weight_kg": 55, "activity_level": "light", "goal": "lose"}
    await client.put("/api/v1/users/me/profile", headers=auth_headers, json=full)
    t = (await client.get("/api/v1/users/me/targets", headers=auth_headers)).json()["data"]
    assert t["basis"] == "profile" and t["calories"] >= 1200  # safe calorie floor
    r = await client.put("/api/v1/users/me/profile", headers=auth_headers, json={"age": None, "country": None})
    assert r.json()["data"]["onboarding_complete"] is False
    assert r.json()["data"]["profile"]["country"] == "IN"  # non-nullable field ignored, not wiped
    t = (await client.get("/api/v1/users/me/targets", headers=auth_headers)).json()["data"]
    assert t["basis"] == "default" and t["calories"] == 2000


async def test_calorie_floor_for_small_user_trying_to_lose(client, auth_headers):
    tiny = {
        "age": 60,
        "sex": "female",
        "height_cm": 140,
        "weight_kg": 35,
        "activity_level": "sedentary",
        "goal": "lose",
    }
    await client.put("/api/v1/users/me/profile", headers=auth_headers, json=tiny)
    t = (await client.get("/api/v1/users/me/targets", headers=auth_headers)).json()["data"]
    assert t["calories"] >= max(1200, t["bmr"])


# ---------------------------------------------------------------------- chat


async def _session(client, headers, **body):
    return (await client.post("/api/v1/chat/sessions", headers=headers, json=body)).json()["data"]


async def _send(client, headers, sid, text=None, image=None):
    files = {"image": ("food.jpg", image, "image/jpeg")} if image else None
    return await client.post(
        f"/api/v1/chat/sessions/{sid}/messages", headers=headers, data={"text": text} if text else {}, files=files
    )


async def test_chat_tools_cannot_read_another_users_scan(
    client, auth_headers, second_user_headers, sample_jpeg, mock_llm
):
    victim_scan = (await create_scan(client, auth_headers, sample_jpeg)).json()["data"]
    sid = (await _session(client, second_user_headers))["id"]
    mock_llm.queue(
        "chat_turn",
        ChatTurn(text=None, function_calls=[FunctionCall("get_scan_details", {"scan_id": victim_scan["id"]}, "c1")]),
    )
    r = await _send(client, second_user_headers, sid, "show me that scan")
    assert r.status_code == 201
    trace = r.json()["data"]["assistant_message"]["tool_calls"][0]
    assert trace["name"] == "get_scan_details"
    history = mock_llm.last_kwargs["chat_turn"]["history"]
    tool_result = next(h for h in history if h.role == "tool").function_results[0].response
    assert tool_result == {"error": "scan not found"}
    assert "Rajma" not in str(history)


async def test_chat_log_meal_only_writes_to_the_callers_intake(client, auth_headers, second_user_headers):
    sid = (await _session(client, auth_headers))["id"]
    r = await _send(client, auth_headers, sid, "log 2 roti and dal for dinner")
    assert r.status_code == 201
    mine = (await client.get("/api/v1/intake/daily", headers=auth_headers)).json()["data"]["entries"]
    theirs = (await client.get("/api/v1/intake/daily", headers=second_user_headers)).json()["data"]["entries"]
    assert len(mine) == 1 and mine[0]["source"] == "chat" and mine[0]["meal_type"] == "dinner"
    assert theirs == []


async def test_image_only_message_titles_the_chat_and_previews_as_photo(client, auth_headers, mock_llm):
    sid = (await _session(client, auth_headers))["id"]
    r = await _send(client, auth_headers, sid, image=make_jpeg())
    assert r.status_code == 201
    user_msg = r.json()["data"]["user_message"]
    assert user_msg["content"] == "" and user_msg["image_url"]
    history = mock_llm.last_kwargs["chat_turn"]["history"]
    assert history[-1].image is not None and history[-1].text  # Gemini gets a prompt, not an empty part
    session = (await client.get(f"/api/v1/chat/sessions/{sid}", headers=auth_headers)).json()["data"]["session"]
    assert session["title"] == "Food photo"


async def test_chat_survives_deleting_the_linked_scan(client, auth_headers, sample_jpeg, mock_llm):
    scan = (await create_scan(client, auth_headers, sample_jpeg)).json()["data"]
    sid = (await _session(client, auth_headers, scan_id=scan["id"]))["id"]
    await client.delete(f"/api/v1/scans/{scan['id']}", headers=auth_headers)
    detail = (await client.get(f"/api/v1/chat/sessions/{sid}", headers=auth_headers)).json()["data"]
    assert detail["session"]["scan_id"] is None
    r = await _send(client, auth_headers, sid, "what next?")
    assert r.status_code == 201
    assert "LINKED MEAL" not in mock_llm.last_kwargs["chat_turn"]["system"]


async def test_chat_prompt_respects_diet_and_allergies(client, auth_headers, mock_llm):
    await client.put(
        "/api/v1/users/me/profile", headers=auth_headers, json={"diet_type": "vegan", "allergies": ["peanuts"]}
    )
    sid = (await _session(client, auth_headers))["id"]
    await _send(client, auth_headers, sid, "cheap protein ideas?")
    system = mock_llm.last_kwargs["chat_turn"]["system"]
    assert "vegan" in system and "peanuts" in system


async def test_chat_ai_failure_keeps_user_message_without_reply(client, auth_headers, mock_llm):
    """Current behaviour: the user's message is committed before Gemini runs, so a 503 leaves it unanswered and
    the next turn sends two consecutive user turns to Gemini (see report, OBS-1)."""
    sid = (await _session(client, auth_headers))["id"]
    mock_llm.queue("chat_turn", AppError("AI_UNAVAILABLE", "down", 503))
    assert (await _send(client, auth_headers, sid, "first try")).status_code == 503
    msgs = (await client.get(f"/api/v1/chat/sessions/{sid}", headers=auth_headers)).json()["data"]["messages"]
    assert [m["role"] for m in msgs] == ["user"]
    assert (await _send(client, auth_headers, sid, "second try")).status_code == 201
    roles = [h.role for h in mock_llm.last_kwargs["chat_turn"]["history"]]
    assert roles[:2] == ["user", "user"]


async def test_chat_session_pagination_and_rename_validation(client, auth_headers):
    for n in range(3):
        await _session(client, auth_headers, title=f"Chat {n}")
    page = (await client.get("/api/v1/chat/sessions?page=2&page_size=2", headers=auth_headers)).json()["data"]
    assert page["total"] == 3 and len(page["items"]) == 1
    sid = page["items"][0]["id"]
    for bad in ({"title": ""}, {"title": "x" * 121}, {}):
        assert (await client.patch(f"/api/v1/chat/sessions/{sid}", headers=auth_headers, json=bad)).status_code == 422


# ---------------------------------------------------------------------- insights


async def test_insight_docs_match_behaviour(client):
    spec = (await client.get("/openapi.json")).json()
    description = spec["paths"]["/api/v1/insights/daily"]["get"]["description"]
    assert "without an AI call" not in description


async def test_insight_for_future_date_is_rejected(client, auth_headers, mock_llm):
    tomorrow = (date.today() + timedelta(days=2)).isoformat()
    r = await client.get(f"/api/v1/insights/daily?date={tomorrow}", headers=auth_headers)
    assert r.status_code == 422 and r.json()["code"] == "VALIDATION_ERROR"
    assert mock_llm.calls["daily_insight"] == 0


async def test_insight_ai_failure_is_503_and_not_cached(client, auth_headers, mock_llm):
    mock_llm.queue("daily_insight", AppError("AI_UNAVAILABLE", "down", 503, {"reason": "quota"}))
    r = await client.get("/api/v1/insights/daily", headers=auth_headers)
    assert r.status_code == 503 and r.json()["details"] == {"reason": "quota"}
    r = await client.get("/api/v1/insights/daily", headers=auth_headers)
    assert r.status_code == 200 and mock_llm.calls["daily_insight"] == 2


# ---------------------------------------------------------------------- database failures


class _BrokenSession:
    async def execute(self, *a, **k):
        raise OperationalError("SELECT 1", {}, Exception("connection refused password=hunter2"))

    scalar = scalars = get = execute

    async def rollback(self):
        return None


def _server_client(app) -> httpx.AsyncClient:
    """A client that gets the 500 response, like a real HTTP client, instead of the re-raised exception."""
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app, raise_app_exceptions=False), base_url="http://t")


async def test_database_outage_returns_500_envelope_without_leaking_details(app, client, auth_headers, monkeypatch):
    async def boom(*a, **k):
        raise OperationalError("SELECT * FROM intake_entries", {}, Exception("password=hunter2"))

    monkeypatch.setattr(intake_service, "daily", boom)
    async with _server_client(app) as c:
        r = await c.get("/api/v1/intake/daily", headers=auth_headers)
    assert r.status_code == 500
    body = r.json()
    assert body == {
        "success": False,
        "code": "INTERNAL_ERROR",
        "message": "Something went wrong on our side. Please try again.",
        "data": None,
        "details": None,
    }
    assert "hunter2" not in r.text and "SELECT" not in r.text


async def test_health_reports_degraded_when_database_is_down(app, client):
    async def broken_db():
        yield _BrokenSession()

    app.dependency_overrides[get_db] = broken_db
    try:
        r = await client.get("/api/v1/health")
    finally:
        app.dependency_overrides.clear()
    assert r.status_code == 200
    assert r.json()["data"]["status"] == "degraded" and r.json()["data"]["db"] == "error"


async def test_authenticated_request_during_db_outage_is_500_not_401(app, client):
    headers = await register_user(client, "Outage")

    async def broken_db():
        yield _BrokenSession()

    app.dependency_overrides[get_db] = broken_db
    try:
        async with _server_client(app) as c:
            r = await c.get("/api/v1/users/me", headers=headers)
    finally:
        app.dependency_overrides.clear()
    assert r.status_code == 500 and r.json()["code"] == "INTERNAL_ERROR"
    assert "hunter2" not in r.text
