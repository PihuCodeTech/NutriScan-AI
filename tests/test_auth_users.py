import jwt

from app.core.config import get_settings


async def test_register_login_me(client):
    r = await client.post(
        "/api/v1/auth/register", json={"email": "Asha@Example.com", "password": "password123", "name": "Asha"}
    )
    assert r.status_code == 201
    body = r.json()
    assert body["code"] == "REGISTERED"
    assert body["data"]["token_type"] == "bearer"
    assert body["data"]["user"]["email"] == "asha@example.com"
    assert body["data"]["user"]["onboarding_complete"] is False

    r = await client.post("/api/v1/auth/login", json={"email": "ASHA@example.com", "password": "password123"})
    assert r.status_code == 200
    assert r.json()["code"] == "LOGGED_IN"
    token = r.json()["data"]["access_token"]

    r = await client.get("/api/v1/users/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    me = r.json()["data"]
    assert me["name"] == "Asha"
    assert me["profile"]["country"] == "IN"
    assert me["profile"]["timezone"] == "Asia/Kolkata"
    assert me["profile"]["allergies"] == []


async def test_duplicate_email(client):
    payload = {"email": "dup@example.com", "password": "password123", "name": "A"}
    assert (await client.post("/api/v1/auth/register", json=payload)).status_code == 201
    r = await client.post("/api/v1/auth/register", json={**payload, "email": "DUP@example.com"})
    assert r.status_code == 409
    assert r.json() == {
        "success": False,
        "code": "EMAIL_TAKEN",
        "message": "An account with this email already exists.",
        "data": None,
        "details": None,
    }


async def test_bad_password(client):
    await client.post("/api/v1/auth/register", json={"email": "b@example.com", "password": "password123", "name": "B"})
    r = await client.post("/api/v1/auth/login", json={"email": "b@example.com", "password": "wrong-password"})
    assert r.status_code == 401
    assert r.json()["code"] == "INVALID_CREDENTIALS"
    r = await client.post("/api/v1/auth/login", json={"email": "nobody@example.com", "password": "whatever1"})
    assert r.status_code == 401
    assert r.json()["code"] == "INVALID_CREDENTIALS"


async def test_register_validation(client):
    r = await client.post("/api/v1/auth/register", json={"email": "not-an-email", "password": "short", "name": ""})
    assert r.status_code == 422
    body = r.json()
    assert body["code"] == "VALIDATION_ERROR"
    fields = {d["loc"][-1] for d in body["details"]}
    assert {"email", "password", "name"} <= fields


async def test_missing_and_invalid_token(client):
    r = await client.get("/api/v1/users/me")
    assert r.status_code == 401
    assert r.json()["code"] == "UNAUTHORIZED"
    r = await client.get("/api/v1/users/me", headers={"Authorization": "Bearer not-a-jwt"})
    assert r.status_code == 401
    assert r.json()["code"] == "UNAUTHORIZED"


async def test_expired_token(client):
    from datetime import UTC, datetime, timedelta

    token = jwt.encode(
        {"sub": "someone", "exp": datetime.now(UTC) - timedelta(minutes=1)}, get_settings().JWT_SECRET, "HS256"
    )
    r = await client.get("/api/v1/users/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 401
    assert r.json()["code"] == "UNAUTHORIZED"


async def test_profile_partial_update(client, auth_headers):
    r = await client.put(
        "/api/v1/users/me/profile", headers=auth_headers, json={"age": 20, "diet_type": "veg", "allergies": ["Peanuts"]}
    )
    assert r.status_code == 200
    body = r.json()
    assert body["code"] == "PROFILE_UPDATED"
    p = body["data"]["profile"]
    assert p["age"] == 20 and p["diet_type"] == "veg" and p["allergies"] == ["Peanuts"]
    assert body["data"]["onboarding_complete"] is False

    r = await client.put(
        "/api/v1/users/me/profile",
        headers=auth_headers,
        json={"sex": "male", "height_cm": 175, "weight_kg": 70, "activity_level": "moderate", "goal": "maintain"},
    )
    data = r.json()["data"]
    assert data["profile"]["age"] == 20  # untouched by the second partial update
    assert data["profile"]["diet_type"] == "veg"
    assert data["onboarding_complete"] is True


async def test_profile_validation(client, auth_headers):
    r = await client.put("/api/v1/users/me/profile", headers=auth_headers, json={"age": 10})
    assert r.status_code == 422
    r = await client.put("/api/v1/users/me/profile", headers=auth_headers, json={"timezone": "Mars/Olympus"})
    assert r.status_code == 422
    r = await client.put("/api/v1/users/me/profile", headers=auth_headers, json={"diet_type": "carnivore"})
    assert r.status_code == 422


async def test_targets_default_and_profile(client, auth_headers):
    r = await client.get("/api/v1/users/me/targets", headers=auth_headers)
    data = r.json()["data"]
    assert data["basis"] == "default"
    assert data["calories"] == 2000

    await client.put(
        "/api/v1/users/me/profile",
        headers=auth_headers,
        json={
            "age": 20,
            "sex": "male",
            "height_cm": 175,
            "weight_kg": 70,
            "activity_level": "moderate",
            "goal": "maintain",
        },
    )
    data = (await client.get("/api/v1/users/me/targets", headers=auth_headers)).json()["data"]
    assert data["basis"] == "profile"
    assert data["calories"] == 2630
    assert data["protein_g"] == 70
    assert data["bmr"] == 1698.75
    assert "sodium_mg" in data["limit_nutrients"]
