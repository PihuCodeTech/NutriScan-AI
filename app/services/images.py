"""Upload validation and normalisation (EXIF-orient, strip metadata, resize, JPEG q=85)."""

from __future__ import annotations

import hashlib
import io
from dataclasses import dataclass

from anyio import to_thread
from fastapi import UploadFile
from PIL import Image, ImageOps, UnidentifiedImageError

from app.core.errors import AppError

ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/jpg", "image/png", "image/webp"}
# Clients that don't set a type (curl -F without ;type=, some mobile libs): let Pillow decide.
LENIENT_CONTENT_TYPES = {"", "application/octet-stream"}
ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP", "MPO"}
MAX_SIDE_PX = 1024
JPEG_QUALITY = 85
MAX_PIXELS = 50_000_000

Image.MAX_IMAGE_PIXELS = MAX_PIXELS


@dataclass(frozen=True)
class NormalizedImage:
    data: bytes  # JPEG bytes
    mime: str
    sha256: str
    width: int
    height: int


def _invalid(message: str = "The file is not a valid JPEG, PNG or WebP image.") -> AppError:
    return AppError("INVALID_IMAGE", message, 400)


def normalize_image_bytes(raw: bytes) -> NormalizedImage:
    """Open with Pillow (rejecting non-images), orient, convert to RGB, resize and re-encode. CPU-bound."""
    try:
        with Image.open(io.BytesIO(raw)) as probe:
            fmt = probe.format
            probe.verify()
        if fmt not in ALLOWED_FORMATS:
            raise _invalid()
        with Image.open(io.BytesIO(raw)) as img:
            img = ImageOps.exif_transpose(img)
            if img.mode in ("RGBA", "LA", "P"):
                rgba = img.convert("RGBA")
                background = Image.new("RGB", rgba.size, (255, 255, 255))
                background.paste(rgba, mask=rgba.split()[-1])
                img = background
            else:
                img = img.convert("RGB")
            img.thumbnail((MAX_SIDE_PX, MAX_SIDE_PX), Image.Resampling.LANCZOS)
            out = io.BytesIO()
            img.save(out, format="JPEG", quality=JPEG_QUALITY, optimize=True)  # no EXIF → metadata stripped
            width, height = img.size
    except AppError:
        raise
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError, Image.DecompressionBombError) as exc:
        raise _invalid() from exc
    data = out.getvalue()
    return NormalizedImage(
        data=data, mime="image/jpeg", sha256=hashlib.sha256(data).hexdigest(), width=width, height=height
    )


async def read_upload(upload: UploadFile, max_bytes: int) -> bytes:
    """Read an upload, enforcing the content type and the size limit."""
    content_type = (upload.content_type or "").split(";")[0].strip().lower()
    if content_type not in ALLOWED_CONTENT_TYPES | LENIENT_CONTENT_TYPES:
        raise _invalid("Only JPEG, PNG or WebP images are accepted.")
    raw = await upload.read(max_bytes + 1)
    if len(raw) > max_bytes:
        raise AppError("FILE_TOO_LARGE", f"Image is larger than {max_bytes // (1024 * 1024)} MB.", 413)
    if not raw:
        raise _invalid("The uploaded file is empty.")
    return raw


async def validate_and_normalise(upload: UploadFile, max_bytes: int) -> NormalizedImage:
    """Full upload pipeline; Pillow work runs in a worker thread."""
    raw = await read_upload(upload, max_bytes)
    return await to_thread.run_sync(normalize_image_bytes, raw)
