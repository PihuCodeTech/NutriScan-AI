import io

import pytest
from PIL import Image

from app.core.errors import AppError
from app.services.images import normalize_image_bytes
from app.services.storage import LocalStorage
from tests.conftest import make_jpeg


def test_normalise_resizes_and_reencodes():
    img = Image.new("RGBA", (3000, 1500), (10, 200, 30, 255))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    out = normalize_image_bytes(buf.getvalue())
    assert out.mime == "image/jpeg"
    assert max(out.width, out.height) == 1024
    assert (out.width, out.height) == (1024, 512)
    assert len(out.sha256) == 64
    reopened = Image.open(io.BytesIO(out.data))
    assert reopened.format == "JPEG" and reopened.mode == "RGB"


def test_normalise_applies_exif_orientation_and_strips_metadata():
    img = Image.new("RGB", (200, 100), (255, 0, 0))
    exif = Image.Exif()
    exif[0x0112] = 6  # rotate 90° CW on display
    buf = io.BytesIO()
    img.save(buf, format="JPEG", exif=exif)
    out = normalize_image_bytes(buf.getvalue())
    assert (out.width, out.height) == (100, 200)
    assert not Image.open(io.BytesIO(out.data)).getexif()


def test_small_image_not_upscaled():
    out = normalize_image_bytes(make_jpeg(256))
    assert (out.width, out.height) == (256, 256)


def test_webp_accepted():
    out = normalize_image_bytes(make_jpeg(64, fmt="WEBP"))
    assert out.mime == "image/jpeg"


@pytest.mark.parametrize("payload", [b"not an image at all", b"%PDF-1.4 fake", b"\x89PNG\r\n\x1a\n broken"])
def test_non_images_rejected(payload):
    with pytest.raises(AppError) as exc:
        normalize_image_bytes(payload)
    assert exc.value.code == "INVALID_IMAGE"


def test_gif_format_rejected():
    buf = io.BytesIO()
    Image.new("RGB", (10, 10)).save(buf, format="GIF")
    with pytest.raises(AppError) as exc:
        normalize_image_bytes(buf.getvalue())
    assert exc.value.code == "INVALID_IMAGE"


async def test_local_storage_roundtrip(tmp_path):
    storage = LocalStorage(str(tmp_path), "http://example.test/")
    rel = await storage.save(b"abc", "jpg")
    assert rel.count("/") == 2 and rel.endswith(".jpg")
    assert await storage.read(rel) == b"abc"
    assert storage.url(rel) == f"http://example.test/media/{rel}"
    await storage.delete(rel)
    assert not (tmp_path / rel).exists()
    with pytest.raises(ValueError):
        storage._abs("../../etc/passwd")


async def test_upload_invalid_file(client, auth_headers):
    r = await client.post("/api/v1/scans", headers=auth_headers, files={"image": ("notes.txt", b"hello", "text/plain")})
    assert r.status_code == 400
    assert r.json()["code"] == "INVALID_IMAGE"
    r = await client.post(
        "/api/v1/scans", headers=auth_headers, files={"image": ("fake.jpg", b"garbage bytes", "image/jpeg")}
    )
    assert r.status_code == 400
    assert r.json()["code"] == "INVALID_IMAGE"


async def test_upload_too_large(client, auth_headers, settings, monkeypatch):
    monkeypatch.setattr(settings, "MAX_UPLOAD_MB", 0.01)  # ~10 KB
    big = make_jpeg(1500)
    assert len(big) > settings.max_upload_bytes
    r = await client.post("/api/v1/scans", headers=auth_headers, files={"image": ("big.jpg", big, "image/jpeg")})
    assert r.status_code == 413
    assert r.json()["code"] == "FILE_TOO_LARGE"


async def test_mock_classifier_used_no_downloads(app):
    from app.services.classifier import MockClassifier

    assert isinstance(app.state.classifier, MockClassifier)
    preds = await app.state.classifier.predict(b"")
    assert preds[0] == {"label": "chicken_curry", "display_name": "Chicken Curry", "score": 0.62}
