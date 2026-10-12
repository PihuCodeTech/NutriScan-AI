from app.services.llm.schemas import InsightLLM


async def _log(client, headers, calories=500):
    nutrients = {"calories": calories, "protein_g": 20, "carbohydrates_g": 60, "fat_g": 15}
    r = await client.post(
        "/api/v1/intake",
        headers=headers,
        json={
            "name": "Lunch",
            "meal_type": "lunch",
            "items": [{"name": "Thali", "quantity_g": 400, "nutrients": nutrients}],
        },
    )
    assert r.status_code == 201


async def test_no_data(client, auth_headers, mock_llm):
    r = await client.get("/api/v1/insights/daily", headers=auth_headers)
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["health_status"] == "no_data"
    assert data["headline"] and data["summary"]
    assert len(data["tips"]) == 3
    assert data["disclaimer"] == "Estimates only — not medical advice."
    assert mock_llm.calls["daily_insight"] == 1  # even an empty day is written by Gemini, not canned text
    again = (await client.get("/api/v1/insights/daily", headers=auth_headers)).json()["data"]
    assert again["headline"] == data["headline"]
    assert mock_llm.calls["daily_insight"] == 1  # cached


async def test_cached_when_totals_unchanged(client, auth_headers, mock_llm):
    await _log(client, auth_headers)
    first = (await client.get("/api/v1/insights/daily", headers=auth_headers)).json()["data"]
    assert mock_llm.calls["daily_insight"] == 1
    assert first["health_status"] in {"on_track", "under"}
    assert len(first["tips"]) == 3

    second = (await client.get("/api/v1/insights/daily", headers=auth_headers)).json()["data"]
    assert mock_llm.calls["daily_insight"] == 1  # served from cache
    assert second == first

    await _log(client, auth_headers, calories=300)  # totals change → new insight
    await client.get("/api/v1/insights/daily", headers=auth_headers)
    assert mock_llm.calls["daily_insight"] == 2


async def test_tips_are_geminis_own_capped_at_three(client, auth_headers, mock_llm):
    await _log(client, auth_headers)
    mock_llm.queue("daily_insight", InsightLLM(headline="Good going", summary="Fine day. Keep it up.", tips=["One"]))
    data = (await client.get("/api/v1/insights/daily", headers=auth_headers)).json()["data"]
    assert data["headline"] == "Good going"
    assert data["tips"] == ["One"]  # never padded with canned tips
    await client.post(
        "/api/v1/intake",
        headers=auth_headers,
        json={"name": "Chai", "meal_type": "snack", "items": [{"name": "Chai", "nutrients": {"calories": 90}}]},
    )
    mock_llm.queue("daily_insight", InsightLLM(headline="Hi", summary="Ok.", tips=[" a ", "b", "", "c", "d"]))
    data = (await client.get("/api/v1/insights/daily", headers=auth_headers)).json()["data"]
    assert data["tips"] == ["a", "b", "c"]


async def test_insight_for_past_date_and_isolation(client, auth_headers, second_user_headers, mock_llm):
    await _log(client, auth_headers)
    other = (await client.get("/api/v1/insights/daily", headers=second_user_headers)).json()["data"]
    assert other["health_status"] == "no_data"
    past = (await client.get("/api/v1/insights/daily?date=2020-01-01", headers=auth_headers)).json()["data"]
    assert past["date"] == "2020-01-01" and past["health_status"] == "no_data"
    assert (await client.get("/api/v1/insights/daily?date=bad", headers=auth_headers)).status_code == 422
