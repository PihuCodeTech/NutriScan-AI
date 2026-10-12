import pytest

from app.services.nutrition import NUTRIENT_KEYS
from tests.conftest import create_scan


async def _scan(client, headers, image):
    r = await create_scan(client, headers, image, meal_type="lunch")
    assert r.status_code == 201
    return r.json()["data"]


def _sum(items, key):
    return sum(i["nutrients"][key] for i in items)


async def test_gram_edit_rescales_linearly(client, auth_headers, sample_jpeg):
    scan = await _scan(client, auth_headers, sample_jpeg)
    rajma = scan["items"][0]
    r = await client.patch(
        f"/api/v1/scans/{scan['id']}/items",
        headers=auth_headers,
        json={"items": [{"id": rajma["id"], "quantity_g": 300}]},
    )
    assert r.status_code == 200, r.text
    assert r.json()["code"] == "SCAN_UPDATED"
    updated = r.json()["data"]
    new = next(i for i in updated["items"] if i["id"] == rajma["id"])
    assert new["quantity_g"] == 300
    assert new["source"] == "user_edit"
    assert new["nutrients"]["calories"] == 2 * rajma["nutrients"]["calories"]
    assert new["nutrients"]["protein_g"] == pytest.approx(2 * rajma["nutrients"]["protein_g"], abs=0.1)
    assert new["nutrients"]["sodium_mg"] == 2 * rajma["nutrients"]["sodium_mg"]
    for key in NUTRIENT_KEYS:
        assert updated["totals"][key] == pytest.approx(_sum(updated["items"], key), abs=0.15)
    assert updated["totals"]["calories"] == scan["totals"]["calories"] + rajma["nutrients"]["calories"]
    assert updated["health"]["tips"] == scan["health"]["tips"]  # tips kept
    assert (
        updated["health"]["score"] != scan["health"]["score"] or updated["health"]["flags"] != scan["health"]["flags"]
    )


async def test_remove_rename_and_add(client, auth_headers, sample_jpeg, mock_llm):
    scan = await _scan(client, auth_headers, sample_jpeg)
    _rajma, rice, salad = scan["items"]
    r = await client.patch(
        f"/api/v1/scans/{scan['id']}/items",
        headers=auth_headers,
        json={
            "items": [
                {"id": salad["id"], "remove": True},
                {"id": rice["id"], "name": "Jeera Rice"},
                {"name": "Curd", "quantity_g": 100},
            ]
        },
    )
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    names = [i["name"] for i in data["items"]]
    assert names == ["Rajma", "Jeera Rice", "Curd"]
    renamed = data["items"][1]
    assert renamed["source"] == "user_edit" and renamed["quantity_g"] == 150
    added = data["items"][2]
    assert added["source"] == "user_added" and added["quantity_g"] == 100
    # curd is in the foods table (60 kcal/100 g), so the server uses that, not the model's 61
    assert added["nutrition_source"] == "table" and added["nutrients"]["calories"] == 60
    assert mock_llm.calls["estimate_from_text"] == 2
    assert mock_llm.last_kwargs["estimate_from_text"]["text"] == "100 g Curd"
    assert data["totals"]["calories"] == pytest.approx(_sum(data["items"], "calories"), abs=1)

    # persisted
    again = (await client.get(f"/api/v1/scans/{scan['id']}", headers=auth_headers)).json()["data"]
    assert [i["name"] for i in again["items"]] == names


async def test_edit_validation(client, auth_headers, sample_jpeg):
    scan = await _scan(client, auth_headers, sample_jpeg)
    url = f"/api/v1/scans/{scan['id']}/items"
    r = await client.patch(url, headers=auth_headers, json={"items": [{"id": "nope", "quantity_g": 10}]})
    assert r.status_code == 404
    r = await client.patch(url, headers=auth_headers, json={"items": [{"id": scan["items"][0]["id"]}]})
    assert r.status_code == 422
    r = await client.patch(url, headers=auth_headers, json={"items": [{"quantity_g": 10}]})
    assert r.status_code == 422
    r = await client.patch(
        url, headers=auth_headers, json={"items": [{"id": scan["items"][0]["id"], "quantity_g": -5}]}
    )
    assert r.status_code == 422
    r = await client.patch(url, headers=auth_headers, json={"items": []})
    assert r.status_code == 422


async def test_regenerate_tips(client, auth_headers, sample_jpeg, mock_llm):
    scan = await _scan(client, auth_headers, sample_jpeg)
    r = await client.post(f"/api/v1/scans/{scan['id']}/tips", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["code"] == "TIPS_UPDATED"
    tips = r.json()["data"]["health"]["tips"]
    assert 2 <= len(tips) <= 3
    assert tips != scan["health"]["tips"]
    assert mock_llm.calls["generate_tips"] == 1
    assert mock_llm.last_kwargs["generate_tips"]["totals"] == scan["totals"]


async def test_log_scan_and_twice_conflicts(client, auth_headers, sample_jpeg):
    scan = await _scan(client, auth_headers, sample_jpeg)
    r = await client.post(f"/api/v1/scans/{scan['id']}/log", headers=auth_headers, json={"meal_type": "dinner"})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["code"] == "INTAKE_LOGGED"
    entry = body["data"]
    assert entry["source"] == "scan" and entry["scan_id"] == scan["id"]
    assert entry["meal_type"] == "dinner"
    assert entry["name"] == "Rajma Chawal Plate"
    assert entry["totals"] == scan["totals"]
    assert len(entry["items"]) == 3

    r = await client.post(f"/api/v1/scans/{scan['id']}/log", headers=auth_headers)
    assert r.status_code == 409
    assert r.json()["code"] == "ALREADY_LOGGED"
    assert (await client.get(f"/api/v1/scans/{scan['id']}", headers=auth_headers)).json()["data"][
        "logged_intake_id"
    ] == entry["id"]

    daily = (await client.get("/api/v1/intake/daily", headers=auth_headers)).json()["data"]
    assert [e["id"] for e in daily["entries"]] == [entry["id"]]

    # deleting the intake entry frees the scan to be logged again
    assert (await client.delete(f"/api/v1/intake/{entry['id']}", headers=auth_headers)).status_code == 200
    assert (await client.post(f"/api/v1/scans/{scan['id']}/log", headers=auth_headers)).status_code == 201


async def test_log_without_body_uses_scan_meal_type(client, auth_headers, sample_jpeg):
    scan = await _scan(client, auth_headers, sample_jpeg)
    entry = (await client.post(f"/api/v1/scans/{scan['id']}/log", headers=auth_headers)).json()["data"]
    assert entry["meal_type"] == "lunch"


async def test_deleting_scan_keeps_intake_entry(client, auth_headers, sample_jpeg):
    scan = await _scan(client, auth_headers, sample_jpeg)
    entry = (await client.post(f"/api/v1/scans/{scan['id']}/log", headers=auth_headers)).json()["data"]
    assert (await client.delete(f"/api/v1/scans/{scan['id']}", headers=auth_headers)).status_code == 200
    daily = (await client.get("/api/v1/intake/daily", headers=auth_headers)).json()["data"]
    assert daily["entries"][0]["id"] == entry["id"]
    assert daily["entries"][0]["scan_id"] is None


async def test_rejected_scan_cannot_be_logged_or_edited(client, auth_headers, sample_jpeg):
    r = await create_scan(client, auth_headers, sample_jpeg, description="not food")
    scan_id = r.json()["details"]["scan_id"]
    assert (await client.post(f"/api/v1/scans/{scan_id}/log", headers=auth_headers)).status_code == 422
    r = await client.patch(f"/api/v1/scans/{scan_id}/items", headers=auth_headers, json={"items": [{"name": "Curd"}]})
    assert r.status_code == 422
