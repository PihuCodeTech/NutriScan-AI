from pathlib import Path

import pytest

from app.core.errors import AppError
from app.services.llm.schemas import FoodAnalysisLLM, LLMFoodItem, LLMNutrients
from app.services.nutrition import NUTRIENT_KEYS
from tests.conftest import create_scan


async def test_scan_happy_path(client, auth_headers, sample_jpeg, mock_llm, settings):
    r = await create_scan(client, auth_headers, sample_jpeg, description="hostel lunch", meal_type="lunch")
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["code"] == "SCAN_CREATED"
    scan = body["data"]
    assert scan["status"] == "completed"
    assert scan["meal_name"] == "Rajma Chawal Plate"
    assert scan["meal_type"] == "lunch"
    assert scan["description"] == "hostel lunch"
    assert len(scan["items"]) >= 1
    assert scan["ai_model"] == "mock-gemini"
    assert scan["logged_intake_id"] is None
    assert scan["created_at"].endswith("Z")

    # server-computed totals equal the sum of items
    for key in NUTRIENT_KEYS:
        assert scan["totals"][key] == pytest.approx(sum(i["nutrients"][key] for i in scan["items"]), abs=0.15)
    assert scan["totals"]["calories"] == 432

    health = scan["health"]
    assert 0 <= health["score"] <= 100
    assert health["label"] in {"good", "moderate", "needs_attention"}
    assert health["color"] in {"green", "amber", "red"}
    assert health["tips"] and health["disclaimer"] == "Estimates only — not medical advice."

    clf = scan["classifier"]
    assert clf["model"] == "nateraw/food"
    assert clf["predictions"][0]["display_name"] == "Chicken Curry"

    item = scan["items"][0]
    assert set(item) == {
        "id",
        "name",
        "canonical_name",
        "quantity_g",
        "serving_description",
        "confidence",
        "source",
        "nutrients",
    }
    assert item["source"] == "ai" and item["confidence"] in {"high", "medium", "low"}

    # hints and description reached the LLM, image stored and served
    kwargs = mock_llm.last_kwargs["analyze_food_image"]
    assert kwargs["hints"][0]["label"] == "chicken_curry"
    assert kwargs["description"] == "hostel lunch"
    assert "Country: IN" in kwargs["user_ctx"]
    assert scan["image_url"].startswith("http://testserver/media/")
    rel = scan["image_url"].split("/media/")[1]
    assert (Path(settings.STORAGE_DIR) / rel).exists()
    media = await client.get(f"/media/{rel}")
    assert media.status_code == 200 and media.headers["content-type"] == "image/jpeg"


async def test_scan_default_meal_type(client, auth_headers, sample_jpeg):
    r = await create_scan(client, auth_headers, sample_jpeg)
    assert r.json()["data"]["meal_type"] in {"breakfast", "lunch", "dinner", "snack"}


async def test_default_meal_type_rules():
    from datetime import datetime

    from app.utils.timeutil import default_meal_type

    def at(h):
        return default_meal_type(datetime(2026, 9, 28, h, 30))

    assert [at(h) for h in (4, 5, 10, 11, 15, 16, 18, 19, 22, 23)] == [
        "snack",
        "breakfast",
        "breakfast",
        "lunch",
        "lunch",
        "snack",
        "snack",
        "dinner",
        "dinner",
        "snack",
    ]


async def test_scan_not_food(client, auth_headers, sample_jpeg):
    r = await create_scan(client, auth_headers, sample_jpeg, description="this is not food")
    assert r.status_code == 422
    body = r.json()
    assert body["code"] == "NOT_FOOD" and body["success"] is False and body["data"] is None
    scan_id = body["details"]["scan_id"]
    stored = await client.get(f"/api/v1/scans/{scan_id}", headers=auth_headers)
    assert stored.status_code == 200
    data = stored.json()["data"]
    assert data["status"] == "rejected"
    assert data["items"] == [] and data["health"] is None


async def test_scan_ai_unavailable_cleans_up_image(client, auth_headers, sample_jpeg, mock_llm, settings):
    mock_llm.queue("analyze_food_image", AppError("AI_UNAVAILABLE", "down", 503))
    r = await create_scan(client, auth_headers, sample_jpeg)
    assert r.status_code == 503
    assert r.json()["code"] == "AI_UNAVAILABLE"
    assert not any(p.is_file() for p in Path(settings.STORAGE_DIR).rglob("*"))


async def test_scan_llm_nutrients_are_sanitised(client, auth_headers, sample_jpeg, mock_llm):
    bogus = FoodAnalysisLLM(
        is_food=True,
        meal_name="Odd",
        items=[
            LLMFoodItem(
                name="Mystery",
                canonical_name="Mystery Dish",
                quantity_g=100,
                serving_description="1 bowl",
                confidence="low",
                nutrients=LLMNutrients(
                    calories=999,
                    protein_g=10,
                    carbohydrates_g=20,
                    fat_g=10,
                    saturated_fat_g=30,
                    fiber_g=-2,
                    sugar_g=50,
                    sodium_mg=100,
                ),
            )
        ],
        tips=["a", "b", "c", "d"],
    )
    mock_llm.queue("analyze_food_image", bogus)
    data = (await create_scan(client, auth_headers, sample_jpeg)).json()["data"]
    n = data["items"][0]["nutrients"]
    assert n["calories"] == 210  # Atwater-corrected
    assert n["saturated_fat_g"] == 10 and n["sugar_g"] == 20 and n["fiber_g"] == 0
    assert data["items"][0]["canonical_name"] == "mystery_dish"
    assert len(data["health"]["tips"]) == 3


async def test_classifier_failure_is_non_fatal(client, auth_headers, sample_jpeg, app):
    async def broken(_bytes):
        return None

    app.state.classifier.predict = broken
    r = await create_scan(client, auth_headers, sample_jpeg)
    assert r.status_code == 201
    assert r.json()["data"]["classifier"] is None


async def test_other_users_scan_is_404(client, auth_headers, second_user_headers, sample_jpeg):
    scan_id = (await create_scan(client, auth_headers, sample_jpeg)).json()["data"]["id"]
    for method, path in [
        ("GET", f"/api/v1/scans/{scan_id}"),
        ("DELETE", f"/api/v1/scans/{scan_id}"),
        ("POST", f"/api/v1/scans/{scan_id}/tips"),
        ("POST", f"/api/v1/scans/{scan_id}/log"),
    ]:
        r = await client.request(method, path, headers=second_user_headers)
        assert r.status_code == 404, (method, path)
        assert r.json()["code"] == "NOT_FOUND"
    r = await client.patch(
        f"/api/v1/scans/{scan_id}/items", headers=second_user_headers, json={"items": [{"name": "Curd"}]}
    )
    assert r.status_code == 404
    assert (await client.get(f"/api/v1/scans/{scan_id}", headers=auth_headers)).status_code == 200


async def test_list_pagination(client, auth_headers, second_user_headers, sample_jpeg):
    ids = [(await create_scan(client, auth_headers, sample_jpeg)).json()["data"]["id"] for _ in range(3)]
    await create_scan(client, second_user_headers, sample_jpeg)

    r = await client.get("/api/v1/scans?page=1&page_size=2", headers=auth_headers)
    page1 = r.json()["data"]
    assert page1["total"] == 3 and page1["page"] == 1 and page1["page_size"] == 2
    assert len(page1["items"]) == 2
    summary = page1["items"][0]
    assert set(summary) == {"id", "status", "image_url", "meal_name", "meal_type", "totals", "health", "created_at"}
    assert set(summary["totals"]) == {"calories"}
    assert set(summary["health"]) == {"score", "label", "color"}

    page2 = (await client.get("/api/v1/scans?page=2&page_size=2", headers=auth_headers)).json()["data"]
    assert len(page2["items"]) == 1
    assert {i["id"] for i in page1["items"] + page2["items"]} == set(ids)
    assert page1["items"][0]["id"] == ids[-1]  # newest first

    assert (await client.get("/api/v1/scans?page_size=101", headers=auth_headers)).status_code == 422


async def test_list_filter_by_date(client, auth_headers, sample_jpeg):
    from datetime import datetime
    from zoneinfo import ZoneInfo

    await create_scan(client, auth_headers, sample_jpeg)
    today = datetime.now(ZoneInfo("Asia/Kolkata")).date().isoformat()
    assert (await client.get(f"/api/v1/scans?date={today}", headers=auth_headers)).json()["data"]["total"] == 1
    assert (await client.get("/api/v1/scans?date=2020-01-01", headers=auth_headers)).json()["data"]["total"] == 0


async def test_delete_scan_removes_image(client, auth_headers, sample_jpeg, settings):
    scan = (await create_scan(client, auth_headers, sample_jpeg)).json()["data"]
    rel = scan["image_url"].split("/media/")[1]
    r = await client.delete(f"/api/v1/scans/{scan['id']}", headers=auth_headers)
    assert r.status_code == 200 and r.json()["code"] == "DELETED" and r.json()["data"] is None
    assert not (Path(settings.STORAGE_DIR) / rel).exists()
    assert (await client.get(f"/api/v1/scans/{scan['id']}", headers=auth_headers)).status_code == 404


async def test_scan_requires_auth_and_image(client, auth_headers, sample_jpeg):
    r = await client.post("/api/v1/scans", files={"image": ("p.jpg", sample_jpeg, "image/jpeg")})
    assert r.status_code == 401
    r = await client.post("/api/v1/scans", headers=auth_headers, data={"description": "x"})
    assert r.status_code == 422 and r.json()["code"] == "VALIDATION_ERROR"
    r = await create_scan(client, auth_headers, sample_jpeg, meal_type="brunch")
    assert r.status_code == 422
