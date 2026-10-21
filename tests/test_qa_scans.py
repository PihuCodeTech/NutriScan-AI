"""QA: the food-scanner journey end to end, plus edge cases in uploads, editing and logging."""

from __future__ import annotations

import asyncio
import io

import pytest
from PIL import Image

from app.core.errors import AppError
from app.services.llm.schemas import FoodAnalysisLLM, LLMFoodItem, LLMNutrients
from app.services.nutrition import NUTRIENT_KEYS
from tests.conftest import create_scan, make_jpeg


def _png_with_alpha() -> bytes:
    img = Image.new("RGBA", (300, 200), (200, 50, 50, 0))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _item(name: str, grams: float, kcal: float = 200, p: float = 10, c: float = 25, f: float = 6) -> LLMFoodItem:
    return LLMFoodItem(
        name=name,
        canonical_name=name.lower().replace(" ", "_"),
        quantity_g=grams,
        serving_description="1 plate",
        confidence="medium",
        nutrients=LLMNutrients(
            calories=kcal,
            protein_g=p,
            carbohydrates_g=c,
            fat_g=f,
            saturated_fat_g=1,
            fiber_g=3,
            sugar_g=2,
            sodium_mg=300,
        ),
    )


async def test_core_journey_scan_edit_tips_log_daily_unlog_relog(client, auth_headers, sample_jpeg, mock_llm):
    """The main business flow a student goes through, checked against the server-side numbers at each step."""
    r = await create_scan(client, auth_headers, sample_jpeg, meal_type="lunch", description="hostel lunch")
    assert r.status_code == 201
    scan = r.json()["data"]
    assert scan["status"] == "completed" and scan["description"] == "hostel lunch"
    assert mock_llm.last_kwargs["analyze_food_image"]["description"] == "hostel lunch"
    assert mock_llm.last_kwargs["analyze_food_image"]["hints"]  # classifier hints reached Gemini

    # Edit: double the first item
    first = scan["items"][0]
    r = await client.patch(
        f"/api/v1/scans/{scan['id']}/items",
        headers=auth_headers,
        json={"items": [{"id": first["id"], "quantity_g": first["quantity_g"] * 2}]},
    )
    edited = r.json()["data"]
    for k in NUTRIENT_KEYS:
        assert edited["totals"][k] == pytest.approx(sum(i["nutrients"][k] for i in edited["items"]), abs=0.15)

    r = await client.post(f"/api/v1/scans/{scan['id']}/tips", headers=auth_headers)
    assert r.status_code == 200 and 1 <= len(r.json()["data"]["health"]["tips"]) <= 3

    # Log → shows up in today's intake with the edited totals
    r = await client.post(f"/api/v1/scans/{scan['id']}/log", headers=auth_headers)
    assert r.status_code == 201
    entry = r.json()["data"]
    assert entry["totals"] == edited["totals"] and entry["source"] == "scan"
    daily = (await client.get("/api/v1/intake/daily", headers=auth_headers)).json()["data"]
    assert [e["id"] for e in daily["entries"]] == [entry["id"]]
    assert daily["totals"] == edited["totals"]
    for k in NUTRIENT_KEYS:
        assert daily["percent_of_target"][k] == round(100 * daily["totals"][k] / daily["targets"][k])

    # Unlog → scan can be logged again
    assert (await client.delete(f"/api/v1/intake/{entry['id']}", headers=auth_headers)).status_code == 200
    assert (await client.get(f"/api/v1/scans/{scan['id']}", headers=auth_headers)).json()["data"][
        "logged_intake_id"
    ] is None
    assert (await client.post(f"/api/v1/scans/{scan['id']}/log", headers=auth_headers)).status_code == 201


async def test_png_with_transparency_and_lenient_content_type(client, auth_headers):
    r = await client.post(
        "/api/v1/scans",
        headers=auth_headers,
        files={"image": ("plate.png", _png_with_alpha(), "application/octet-stream")},
    )
    assert r.status_code == 201, r.text


@pytest.mark.parametrize(
    ("filename", "payload", "content_type", "status", "code"),
    [
        ("doc.pdf", b"%PDF-1.4 fake", "application/pdf", 400, "INVALID_IMAGE"),
        ("plate.jpg", b"", "image/jpeg", 400, "INVALID_IMAGE"),
        ("plate.jpg", b"\xff\xd8\xff\xe0 truncated jpeg", "image/jpeg", 400, "INVALID_IMAGE"),
        ("anim.gif", b"GIF89a" + b"\x00" * 50, "image/png", 400, "INVALID_IMAGE"),  # lies about its type
    ],
)
async def test_invalid_uploads(client, auth_headers, mock_llm, filename, payload, content_type, status, code):
    r = await client.post("/api/v1/scans", headers=auth_headers, files={"image": (filename, payload, content_type)})
    assert r.status_code == status and r.json()["code"] == code
    assert r.json()["success"] is False and r.json()["data"] is None
    assert mock_llm.calls["analyze_food_image"] == 0  # never paid for a Gemini call


async def test_invalid_meal_type_and_too_long_description(client, auth_headers, sample_jpeg):
    r = await create_scan(client, auth_headers, sample_jpeg, meal_type="brunch")
    assert r.status_code == 422 and r.json()["code"] == "VALIDATION_ERROR"
    r = await create_scan(client, auth_headers, sample_jpeg, description="x" * 301)
    assert r.status_code == 422


async def test_failed_upload_leaves_no_files_behind(client, auth_headers, sample_jpeg, mock_llm, settings):
    from pathlib import Path

    mock_llm.queue("analyze_food_image", AppError("AI_UNAVAILABLE", "down", 503))
    r = await create_scan(client, auth_headers, sample_jpeg)
    assert r.status_code == 503
    assert not [p for p in Path(settings.STORAGE_DIR).rglob("*") if p.is_file()]
    assert (await client.get("/api/v1/scans", headers=auth_headers)).json()["data"]["total"] == 0


async def test_rejected_scan_is_listed_and_deletable(client, auth_headers, sample_jpeg):
    r = await create_scan(client, auth_headers, sample_jpeg, description="not food")
    assert r.status_code == 422
    scan_id = r.json()["details"]["scan_id"]
    listing = (await client.get("/api/v1/scans", headers=auth_headers)).json()["data"]
    assert listing["items"][0]["id"] == scan_id and listing["items"][0]["status"] == "rejected"
    assert listing["items"][0]["health"] is None
    r = await client.post(f"/api/v1/scans/{scan_id}/tips", headers=auth_headers)
    assert r.status_code == 422
    assert (await client.delete(f"/api/v1/scans/{scan_id}", headers=auth_headers)).status_code == 200


async def test_empty_items_from_gemini_is_not_food(client, auth_headers, sample_jpeg, mock_llm):
    mock_llm.queue("analyze_food_image", FoodAnalysisLLM(is_food=True, items=[]))
    r = await create_scan(client, auth_headers, sample_jpeg)
    assert r.status_code == 422 and r.json()["code"] == "NOT_FOOD"


async def test_pagination_past_the_end_and_bounds(client, auth_headers, sample_jpeg):
    await create_scan(client, auth_headers, sample_jpeg)
    r = await client.get("/api/v1/scans?page=5&page_size=10", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["data"]["items"] == [] and r.json()["data"]["total"] == 1
    for q in ("page=0", "page_size=0", "page_size=101", "page=abc", "date=2026-13-01"):
        assert (await client.get(f"/api/v1/scans?{q}", headers=auth_headers)).status_code == 422, q


async def test_unknown_item_id_in_patch_is_404(client, auth_headers, sample_jpeg):
    scan = (await create_scan(client, auth_headers, sample_jpeg)).json()["data"]
    r = await client.patch(
        f"/api/v1/scans/{scan['id']}/items", headers=auth_headers, json={"items": [{"id": "nope", "quantity_g": 10}]}
    )
    assert r.status_code == 404


async def test_patch_is_atomic_when_a_later_edit_fails(client, auth_headers, sample_jpeg):
    """First edit removes an item, the second references it again → 404, and nothing must be saved."""
    scan = (await create_scan(client, auth_headers, sample_jpeg)).json()["data"]
    a, b = scan["items"][0], scan["items"][1]
    r = await client.patch(
        f"/api/v1/scans/{scan['id']}/items",
        headers=auth_headers,
        json={
            "items": [
                {"id": b["id"], "quantity_g": 999},
                {"id": a["id"], "remove": True},
                {"id": a["id"], "quantity_g": 5},
            ]
        },
    )
    assert r.status_code == 404
    after = (await client.get(f"/api/v1/scans/{scan['id']}", headers=auth_headers)).json()["data"]
    assert after["items"] == scan["items"] and after["totals"] == scan["totals"]


async def test_patch_is_atomic_when_gemini_fails_midway(client, auth_headers, sample_jpeg, mock_llm):
    scan = (await create_scan(client, auth_headers, sample_jpeg)).json()["data"]
    mock_llm.queue("estimate_from_text", AppError("AI_UNAVAILABLE", "down", 503))
    r = await client.patch(
        f"/api/v1/scans/{scan['id']}/items",
        headers=auth_headers,
        json={"items": [{"id": scan["items"][0]["id"], "remove": True}, {"name": "Curd", "quantity_g": 100}]},
    )
    assert r.status_code == 503
    after = (await client.get(f"/api/v1/scans/{scan['id']}", headers=auth_headers)).json()["data"]
    assert len(after["items"]) == len(scan["items"])


async def test_renamed_item_that_is_not_food_is_rejected(client, auth_headers, sample_jpeg):
    scan = (await create_scan(client, auth_headers, sample_jpeg)).json()["data"]
    r = await client.patch(
        f"/api/v1/scans/{scan['id']}/items",
        headers=auth_headers,
        json={"items": [{"id": scan["items"][0]["id"], "name": "not food at all"}]},
    )
    assert r.status_code == 422 and r.json()["code"] == "NOT_FOOD"


async def test_removing_every_item_is_refused(client, auth_headers, sample_jpeg):
    scan = (await create_scan(client, auth_headers, sample_jpeg)).json()["data"]
    r = await client.patch(
        f"/api/v1/scans/{scan['id']}/items",
        headers=auth_headers,
        json={"items": [{"id": i["id"], "remove": True} for i in scan["items"]]},
    )
    assert r.status_code == 422 and r.json()["code"] == "VALIDATION_ERROR"
    after = (await client.get(f"/api/v1/scans/{scan['id']}", headers=auth_headers)).json()["data"]
    assert after["items"] == scan["items"]  # nothing was removed


async def test_gram_edit_keeps_nutrients_when_ai_reported_zero_grams(client, auth_headers, sample_jpeg, mock_llm):
    mock_llm.queue(
        "analyze_food_image",
        FoodAnalysisLLM(is_food=True, meal_name="Mystery curry", items=[_item("Mystery Curry", 0, kcal=200)]),
    )
    scan = (await create_scan(client, auth_headers, sample_jpeg)).json()["data"]
    item = scan["items"][0]
    assert item["nutrients"]["calories"] > 0
    r = await client.patch(
        f"/api/v1/scans/{scan['id']}/items",
        headers=auth_headers,
        json={"items": [{"id": item["id"], "quantity_g": 250}]},
    )
    edited = r.json()["data"]["items"][0]
    assert edited["nutrients"]["calories"] == pytest.approx(2.5 * item["nutrients"]["calories"], abs=1)
    assert item["quantity_g"] == 100 and item["confidence"] == "low"  # 100 g reference portion, flagged


async def test_scan_list_and_detail_hide_other_users_and_order_newest_first(client, auth_headers, sample_jpeg):
    ids = [(await create_scan(client, auth_headers, make_jpeg(200 + n))).json()["data"]["id"] for n in range(3)]
    listing = (await client.get("/api/v1/scans", headers=auth_headers)).json()["data"]
    assert [s["id"] for s in listing["items"]] == list(reversed(ids))


async def test_concurrent_log_of_one_scan_creates_one_entry(client, auth_headers, sample_jpeg):

    scan = (await create_scan(client, auth_headers, sample_jpeg)).json()["data"]
    responses = await asyncio.gather(
        *[client.post(f"/api/v1/scans/{scan['id']}/log", headers=auth_headers) for _ in range(3)]
    )
    assert sorted(r.status_code for r in responses) == [201, 409, 409]
    daily = (await client.get("/api/v1/intake/daily", headers=auth_headers)).json()["data"]
    assert len(daily["entries"]) == 1
