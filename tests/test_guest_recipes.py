"""Guest sessions are real accounts (so guests get real AI), and Gemini meal ideas from ingredients."""

from __future__ import annotations

from app.core.errors import AppError
from app.services.llm.schemas import LLMNutrients, LLMRecipe, RecipesLLM


async def test_guest_session_is_a_real_account(client, mock_llm, sample_jpeg):
    r = await client.post("/api/v1/auth/guest")
    assert r.status_code == 201
    body = r.json()
    assert body["code"] == "GUEST_CREATED"
    user = body["data"]["user"]
    assert user["is_guest"] is True and user["name"] == "Guest"
    headers = {"Authorization": "Bearer " + body["data"]["access_token"]}

    me = (await client.get("/api/v1/users/me", headers=headers)).json()["data"]
    assert me["is_guest"] is True
    scan = await client.post("/api/v1/scans", headers=headers, files={"image": ("p.jpg", sample_jpeg, "image/jpeg")})
    assert scan.status_code == 201  # guests go through the real AI pipeline
    assert mock_llm.calls["analyze_food_image"] == 1


async def test_each_guest_gets_a_separate_account(client):
    a = (await client.post("/api/v1/auth/guest")).json()["data"]["user"]["id"]
    b = (await client.post("/api/v1/auth/guest")).json()["data"]["user"]["id"]
    assert a != b


async def test_registered_user_is_not_guest(client, auth_headers):
    assert (await client.get("/api/v1/users/me", headers=auth_headers)).json()["data"]["is_guest"] is False


async def test_recipes_suggest(client, auth_headers, mock_llm):
    r = await client.post(
        "/api/v1/recipes/suggest",
        headers=auth_headers,
        json={"ingredients": ["poha", " onion ", "poha", "peanuts"], "kitchen": "burner", "count": 3},
    )
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert len(data["meals"]) == 3
    meal = data["meals"][0]
    assert {"name", "why", "time_minutes", "kitchen", "ingredients", "steps", "nutrients"} <= meal.keys()
    assert set(meal["nutrients"]) == {
        "calories",
        "protein_g",
        "carbohydrates_g",
        "fat_g",
        "saturated_fat_g",
        "fiber_g",
        "sugar_g",
        "sodium_mg",
    }
    assert data["disclaimer"]
    assert mock_llm.last_kwargs["suggest_recipes"]["ingredients"] == ["poha", "onion", "peanuts"]


def _recipe(kitchen: str, calories: float = 9999) -> LLMRecipe:
    n = LLMNutrients(
        calories=calories,
        protein_g=10,
        carbohydrates_g=40,
        fat_g=5,
        saturated_fat_g=9,
        fiber_g=3,
        sugar_g=2,
        sodium_mg=300,
    )
    return LLMRecipe(
        name=f"{kitchen} dish",
        why="ok",
        time_minutes=10,
        kitchen=kitchen,
        ingredients=["oats"],
        steps=["Mix."],
        nutrients=n,
    )


async def test_recipes_respect_kitchen_and_sanitise_nutrients(client, auth_headers, mock_llm):
    mock_llm.queue("suggest_recipes", RecipesLLM(recipes=[_recipe("burner"), _recipe("kettle")]))
    r = await client.post(
        "/api/v1/recipes/suggest", headers=auth_headers, json={"ingredients": ["oats"], "kitchen": "kettle"}
    )
    meals = r.json()["data"]["meals"]
    assert [m["kitchen"] for m in meals] == ["kettle"]  # the burner recipe is dropped
    n = meals[0]["nutrients"]
    assert n["calories"] == 245  # Atwater-corrected from 9999
    assert n["saturated_fat_g"] == 5  # capped at total fat


async def test_recipes_none_fit_is_an_error(client, auth_headers, mock_llm):
    mock_llm.queue("suggest_recipes", RecipesLLM(recipes=[_recipe("burner")]))
    r = await client.post(
        "/api/v1/recipes/suggest", headers=auth_headers, json={"ingredients": ["oats"], "kitchen": "none"}
    )
    assert r.status_code == 502 and r.json()["code"] == "AI_BAD_RESPONSE"


async def test_recipes_validation_and_ai_errors(client, auth_headers, mock_llm):
    bad = await client.post("/api/v1/recipes/suggest", headers=auth_headers, json={"ingredients": ["  "]})
    assert bad.status_code == 422
    assert (await client.post("/api/v1/recipes/suggest", json={"ingredients": ["oats"]})).status_code == 401
    mock_llm.queue("suggest_recipes", AppError("AI_UNAVAILABLE", "quota", 503, {"reason": "quota"}))
    r = await client.post("/api/v1/recipes/suggest", headers=auth_headers, json={"ingredients": ["oats"]})
    assert r.status_code == 503 and r.json()["details"] == {"reason": "quota"}
