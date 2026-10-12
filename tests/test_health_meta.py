async def test_health(client):
    r = await client.get("/api/v1/health")
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True and body["code"] == "OK"
    data = body["data"]
    assert data["status"] == "ok"
    assert data["db"] == "ok"
    assert data["classifier"] == "loaded"
    assert data["gemini"] == "mock"
    assert data["version"]
    assert r.headers.get("x-request-id")


async def test_request_id_is_echoed(client):
    r = await client.get("/api/v1/health", headers={"X-Request-ID": "abc123"})
    assert r.headers["x-request-id"] == "abc123"


async def test_meta(client):
    r = await client.get("/api/v1/meta")
    assert r.status_code == 200
    data = r.json()["data"]
    keys = [n["key"] for n in data["nutrients"]]
    assert keys == [
        "calories",
        "protein_g",
        "carbohydrates_g",
        "fat_g",
        "saturated_fat_g",
        "fiber_g",
        "sugar_g",
        "sodium_mg",
    ]
    units = {n["key"]: n["unit"] for n in data["nutrients"]}
    assert units["calories"] == "kcal" and units["sodium_mg"] == "mg" and units["protein_g"] == "g"
    assert {m["value"] for m in data["meal_types"]} == {"breakfast", "lunch", "dinner", "snack"}
    assert {d["value"] for d in data["diet_types"]} == {"veg", "eggetarian", "non_veg", "vegan"}
    assert [h["color"] for h in data["health_labels"]] == ["green", "amber", "red"]
    assert data["disclaimer"] == "Estimates only — not medical advice."
    assert data["max_upload_mb"] == 8


async def test_docs_and_openapi(client):
    r = await client.get("/openapi.json")
    assert r.status_code == 200
    spec = r.json()
    assert {t["name"] for t in spec["tags"]} == {
        "system",
        "auth",
        "users",
        "scans",
        "intake",
        "insights",
        "chat",
        "recipes",
    }
    assert "/api/v1/scans" in spec["paths"]
    for path, ops in spec["paths"].items():
        for method, op in ops.items():
            assert op.get("summary"), f"{method} {path} has no summary"
            assert op.get("description"), f"{method} {path} has no description"
    assert (await client.get("/docs")).status_code == 200


async def test_health_with_classifier_disabled(settings, monkeypatch):
    import httpx

    from app.main import create_app

    monkeypatch.setattr(settings, "CLASSIFIER_ENABLED", False)
    app = create_app(settings)
    transport = httpx.ASGITransport(app=app)
    async with app.router.lifespan_context(app), httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        r = await c.get("/api/v1/health")
    assert r.json()["data"]["classifier"] == "disabled"


async def test_web_app_is_served_without_stale_caching(client):
    root = await client.get("/")
    assert root.status_code == 307 and root.headers["location"] == "/app/"
    for path in ("/app/", "/app/app.js", "/app/config.js"):
        r = await client.get(path)
        assert r.status_code == 200, path
        assert r.headers["cache-control"] == "no-cache", path
    assert "cache-control" not in (await client.get("/api/v1/health")).headers
