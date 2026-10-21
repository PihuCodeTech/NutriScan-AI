"""QA: authentication, authorisation and signed media URLs."""

from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlparse

import jwt
import pytest
from sqlalchemy import select

from app.db.models import User
from app.db.session import get_sessionmaker
from app.services import maintenance
from tests.conftest import create_scan


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def test_forged_tokens_are_rejected(client, auth_headers, settings):
    me = (await client.get("/api/v1/users/me", headers=auth_headers)).json()["data"]
    now = datetime.now(UTC)
    claims = {"sub": me["id"], "iat": now, "exp": now + timedelta(hours=1)}
    forged = [
        jwt.encode(claims, "wrong-secret-wrong-secret-wrong-secret", algorithm="HS256"),
        jwt.encode(claims, None, algorithm="none"),  # alg=none must never be accepted
        jwt.encode({**claims, "sub": 12345}, settings.JWT_SECRET, algorithm="HS256"),  # non-string subject
        jwt.encode({"iat": now, "exp": now + timedelta(hours=1)}, settings.JWT_SECRET, algorithm="HS256"),
        "not.a.jwt",
    ]
    for token in forged:
        r = await client.get("/api/v1/users/me", headers=_bearer(token))
        assert r.status_code == 401, token
        body = r.json()
        assert body["success"] is False and body["code"] == "UNAUTHORIZED" and body["data"] is None


async def test_wrong_auth_scheme_and_valid_token_for_unknown_user(client, settings):
    r = await client.get("/api/v1/users/me", headers={"Authorization": "Basic dXNlcjpwYXNz"})
    assert r.status_code == 401 and r.json()["code"] == "UNAUTHORIZED"
    ghost = jwt.encode(
        {"sub": str(uuid.uuid4()), "exp": datetime.now(UTC) + timedelta(hours=1)}, settings.JWT_SECRET, "HS256"
    )
    r = await client.get("/api/v1/users/me", headers=_bearer(ghost))
    assert r.status_code == 401 and r.json()["code"] == "UNAUTHORIZED"


async def test_login_is_case_insensitive_and_trims_email(client):
    email = f"MiXeD-{uuid.uuid4().hex[:6]}@Example.com"
    r = await client.post("/api/v1/auth/register", json={"email": email, "password": "password123", "name": "M"})
    assert r.status_code == 201
    assert r.json()["data"]["user"]["email"] == email.lower()
    r = await client.post("/api/v1/auth/login", json={"email": email.upper(), "password": "password123"})
    assert r.status_code == 200 and r.json()["code"] == "LOGGED_IN"
    # Same email in a different case is a duplicate
    r = await client.post(
        "/api/v1/auth/register", json={"email": email.lower(), "password": "password123", "name": "M"}
    )
    assert r.status_code == 409 and r.json()["code"] == "EMAIL_TAKEN"


async def test_login_error_does_not_reveal_whether_email_exists(client):
    email = f"known-{uuid.uuid4().hex[:6]}@example.com"
    await client.post("/api/v1/auth/register", json={"email": email, "password": "password123", "name": "K"})
    wrong_pw = await client.post("/api/v1/auth/login", json={"email": email, "password": "nope-nope"})
    no_user = await client.post("/api/v1/auth/login", json={"email": "nobody@example.com", "password": "nope-nope"})
    assert wrong_pw.status_code == no_user.status_code == 401
    assert wrong_pw.json()["message"] == no_user.json()["message"]


async def test_passwords_longer_than_bcrypts_72_bytes_are_refused(client):
    """bcrypt ignores everything after 72 bytes, so such passwords would match on their prefix alone."""
    email = f"long-{uuid.uuid4().hex[:6]}@example.com"
    r = await client.post(
        "/api/v1/auth/register", json={"email": email, "password": "a" * 72 + "SECRET-TAIL", "name": "L"}
    )
    assert r.status_code == 422 and r.json()["details"][0]["loc"] == ["body", "password"]
    r = await client.post("/api/v1/auth/register", json={"email": email, "password": "é" * 37, "name": "L"})
    assert r.status_code == 422  # 37 characters but 74 bytes
    r = await client.post("/api/v1/auth/register", json={"email": email, "password": "a" * 72, "name": "L"})
    assert r.status_code == 201
    r = await client.post("/api/v1/auth/login", json={"email": email, "password": "a" * 71 + "b"})
    assert r.status_code == 401


async def test_registering_on_the_guest_domain_is_rejected(client):
    r = await client.post(
        "/api/v1/auth/register",
        json={
            "email": f"real-person-{uuid.uuid4().hex[:6]}@guest.nutriscan.app",
            "password": "password123",
            "name": "R",
        },
    )
    assert r.status_code == 422 and r.json()["details"][0]["loc"] == ["body", "email"]


async def test_guest_sessions_still_work_on_the_reserved_domain(client):
    r = await client.post("/api/v1/auth/guest")
    assert r.status_code == 201 and r.json()["data"]["user"]["is_guest"] is True


async def test_deleted_guest_token_stops_working(client, app):
    r = await client.post("/api/v1/auth/guest")
    token = r.json()["data"]["access_token"]
    async with get_sessionmaker()() as db:
        user = await db.scalar(select(User).where(User.id == r.json()["data"]["user"]["id"]))
        user.created_at = datetime.now(UTC) - timedelta(days=10)
        await db.commit()
        await maintenance.cleanup_guests(db, app.state.storage, retention_days=3)
    r = await client.get("/api/v1/users/me", headers=_bearer(token))
    assert r.status_code == 401 and r.json()["code"] == "UNAUTHORIZED"


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/v1/users/me"),
        ("PUT", "/api/v1/users/me/profile"),
        ("GET", "/api/v1/users/me/targets"),
        ("GET", "/api/v1/scans"),
        ("POST", "/api/v1/scans"),
        ("GET", "/api/v1/scans/x"),
        ("PATCH", "/api/v1/scans/x/items"),
        ("POST", "/api/v1/scans/x/tips"),
        ("POST", "/api/v1/scans/x/log"),
        ("DELETE", "/api/v1/scans/x"),
        ("GET", "/api/v1/intake"),
        ("POST", "/api/v1/intake"),
        ("POST", "/api/v1/intake/describe"),
        ("GET", "/api/v1/intake/daily"),
        ("GET", "/api/v1/intake/summary"),
        ("DELETE", "/api/v1/intake/x"),
        ("GET", "/api/v1/insights/daily"),
        ("GET", "/api/v1/chat/suggestions"),
        ("GET", "/api/v1/chat/sessions"),
        ("POST", "/api/v1/chat/sessions"),
        ("GET", "/api/v1/chat/sessions/x"),
        ("PATCH", "/api/v1/chat/sessions/x"),
        ("DELETE", "/api/v1/chat/sessions/x"),
        ("POST", "/api/v1/chat/sessions/x/messages"),
        ("POST", "/api/v1/chat/sessions/x/messages/stream"),
        ("POST", "/api/v1/recipes/suggest"),
    ],
)
async def test_every_private_endpoint_requires_auth(client, method, path):
    r = await client.request(method, path)
    assert r.status_code == 401, (method, path, r.status_code)
    assert r.json()["code"] == "UNAUTHORIZED"


async def test_cross_user_mutations_are_404_and_leave_data_untouched(
    client, auth_headers, second_user_headers, sample_jpeg
):
    scan = (await create_scan(client, auth_headers, sample_jpeg, meal_type="lunch")).json()["data"]
    sid, item_id = scan["id"], scan["items"][0]["id"]
    attacker = second_user_headers
    attempts = [
        client.patch(f"/api/v1/scans/{sid}/items", headers=attacker, json={"items": [{"id": item_id, "remove": True}]}),
        client.post(f"/api/v1/scans/{sid}/tips", headers=attacker),
        client.post(f"/api/v1/scans/{sid}/log", headers=attacker),
        client.delete(f"/api/v1/scans/{sid}", headers=attacker),
        client.post("/api/v1/chat/sessions", headers=attacker, json={"scan_id": sid}),
        client.get(f"/api/v1/chat/suggestions?scan_id={sid}", headers=attacker),
    ]
    for coro in attempts:
        r = await coro
        assert r.status_code == 404, r.text
    after = (await client.get(f"/api/v1/scans/{sid}", headers=auth_headers)).json()["data"]
    assert len(after["items"]) == len(scan["items"]) and after["logged_intake_id"] is None


async def test_rate_limit_is_per_user(client, auth_headers, second_user_headers, settings, monkeypatch):
    monkeypatch.setattr(settings, "RATE_LIMIT_AI", "2/minute")
    body = {"text": "2 roti and dal"}
    for _ in range(2):
        assert (await client.post("/api/v1/intake/describe", headers=auth_headers, json=body)).status_code == 200
    r = await client.post("/api/v1/intake/describe", headers=auth_headers, json=body)
    assert r.status_code == 429 and r.json()["code"] == "RATE_LIMITED"
    # Another user is not affected by the first user's usage
    assert (await client.post("/api/v1/intake/describe", headers=second_user_headers, json=body)).status_code == 200


# ---------------------------------------------------------------------- signed media URLs


def _split_media_url(url: str) -> tuple[str, int, str]:
    parsed = urlparse(url)
    q = parse_qs(parsed.query)
    return parsed.path, int(q["exp"][0]), q["sig"][0]


async def test_signed_media_url_serves_the_image(client, auth_headers, sample_jpeg):
    scan = (await create_scan(client, auth_headers, sample_jpeg)).json()["data"]
    path, exp, sig = _split_media_url(scan["image_url"])
    r = await client.get(path, params={"exp": exp, "sig": sig})
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/jpeg" and r.content[:2] == b"\xff\xd8"


async def test_media_rejects_tampered_expired_and_unsigned_links(client, auth_headers, sample_jpeg, settings):
    from app.core import media

    scan = (await create_scan(client, auth_headers, sample_jpeg)).json()["data"]
    path, exp, sig = _split_media_url(scan["image_url"])
    rel = path.removeprefix("/api/v1/media/")

    assert (await client.get(path, params={"exp": exp, "sig": "0" * 64})).status_code == 403
    assert (await client.get(path, params={"exp": exp + 1, "sig": sig})).status_code == 403  # exp is signed
    past = int(time.time()) - 10
    expired_sig = media._sig(rel, past, settings.JWT_SECRET)
    r = await client.get(path, params={"exp": past, "sig": expired_sig})
    assert r.status_code == 403 and r.json()["code"] == "FORBIDDEN"
    r = await client.get(path)
    assert r.status_code == 422 and r.json()["code"] == "VALIDATION_ERROR"


async def test_media_signature_cannot_be_reused_for_another_file(
    client, auth_headers, second_user_headers, sample_jpeg
):
    mine = (await create_scan(client, auth_headers, sample_jpeg)).json()["data"]
    theirs = (await create_scan(client, second_user_headers, sample_jpeg)).json()["data"]
    _, exp, sig = _split_media_url(mine["image_url"])
    their_path, _, _ = _split_media_url(theirs["image_url"])
    assert (await client.get(their_path, params={"exp": exp, "sig": sig})).status_code == 403


async def test_media_path_traversal_is_blocked_even_with_a_valid_signature(client, settings, tmp_path):
    from app.core import media

    secret_file = tmp_path / "secret.txt"
    secret_file.write_text("top secret")
    rel = "../secret.txt"  # STORAGE_DIR is tmp_path/uploads
    exp, sig = media.sign(rel, settings.JWT_SECRET, 60)
    r = await client.get(f"/api/v1/media/{rel}", params={"exp": exp, "sig": sig})
    assert r.status_code in {404, 403}
    assert b"top secret" not in r.content


async def test_media_for_deleted_scan_is_404(client, auth_headers, sample_jpeg):
    scan = (await create_scan(client, auth_headers, sample_jpeg)).json()["data"]
    path, exp, sig = _split_media_url(scan["image_url"])
    assert (await client.delete(f"/api/v1/scans/{scan['id']}", headers=auth_headers)).status_code == 200
    r = await client.get(path, params={"exp": exp, "sig": sig})
    assert r.status_code == 404 and r.json()["code"] == "NOT_FOUND"
