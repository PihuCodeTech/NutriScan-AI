"""Every error, handled or not, uses the envelope; rate limits; no stack traces leak."""

import httpx
from fastapi import APIRouter

from tests.conftest import create_scan


async def test_unknown_route_404_envelope(client):
    r = await client.get("/api/v1/does-not-exist")
    assert r.status_code == 404
    assert r.json() == {"success": False, "code": "NOT_FOUND", "message": "Not found.", "data": None, "details": None}


async def test_method_not_allowed_envelope(client):
    r = await client.put("/api/v1/health")
    assert r.status_code == 405
    body = r.json()
    assert body["success"] is False and body["code"] == "METHOD_NOT_ALLOWED" and body["data"] is None


async def test_validation_error_envelope(client, auth_headers):
    r = await client.post("/api/v1/intake/describe", headers=auth_headers, json={"text": ""})
    assert r.status_code == 422
    body = r.json()
    assert body["code"] == "VALIDATION_ERROR" and body["data"] is None
    assert body["details"][0]["loc"] == ["body", "text"]
    r = await client.post("/api/v1/intake/describe", headers=auth_headers, content=b"{not json", timeout=5)
    assert r.status_code == 422 and r.json()["code"] == "VALIDATION_ERROR"


async def test_unhandled_exception_is_500_without_trace(app, settings):
    boom = APIRouter()

    @boom.get("/api/v1/boom")
    async def _boom() -> None:
        raise RuntimeError("secret internal detail")

    app.include_router(boom)
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
        r = await c.get("/api/v1/boom")
    assert r.status_code == 500
    body = r.json()
    assert body["code"] == "INTERNAL_ERROR" and body["success"] is False
    assert "secret" not in r.text and "Traceback" not in r.text


async def test_rate_limit_on_ai_endpoints(
    client, auth_headers, second_user_headers, settings, monkeypatch, sample_jpeg
):
    monkeypatch.setattr(settings, "RATE_LIMIT_AI", "2/minute")
    for _ in range(2):
        r = await client.post("/api/v1/intake/describe", headers=auth_headers, json={"text": "dal rice"})
        assert r.status_code == 200
    r = await client.post("/api/v1/intake/describe", headers=auth_headers, json={"text": "dal rice"})
    assert r.status_code == 429
    body = r.json()
    assert body["code"] == "RATE_LIMITED" and body["success"] is False and body["data"] is None
    # per user: another user still has budget
    r = await client.post("/api/v1/intake/describe", headers=second_user_headers, json={"text": "dal rice"})
    assert r.status_code == 200
    # scans are limited too
    for _ in range(2):
        assert (await create_scan(client, second_user_headers, sample_jpeg)).status_code == 201
    assert (await create_scan(client, second_user_headers, sample_jpeg)).status_code == 429


async def test_cors_headers(client):
    r = await client.options(
        "/api/v1/health",
        headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "GET"},
    )
    assert r.status_code == 200
    assert r.headers["access-control-allow-origin"] in {"*", "http://localhost:5173"}


async def test_logs_do_not_contain_secrets(client, auth_headers, sample_jpeg, caplog, settings):
    import logging

    caplog.set_level(logging.INFO)
    await create_scan(client, auth_headers, sample_jpeg)
    text = caplog.text
    assert settings.JWT_SECRET not in text
    assert auth_headers["Authorization"].split()[1] not in text
    assert "\\xff\\xd8" not in text  # no raw JPEG bytes
