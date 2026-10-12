"""Serve uploaded photos only through signed, time-limited URLs (see app/core/media.py)."""

from __future__ import annotations

from fastapi import APIRouter, Query, Request, Response

from app.api.deps import SettingsDep, StorageDep
from app.core import media
from app.core.errors import AppError, not_found

router = APIRouter(prefix="/media", tags=["system"], include_in_schema=False)


@router.get("/{rel_path:path}")
async def get_media(
    rel_path: str,
    request: Request,
    storage: StorageDep,
    settings: SettingsDep,
    exp: int = Query(...),
    sig: str = Query(...),
) -> Response:
    if not media.verify(rel_path, exp, sig, settings.JWT_SECRET):
        raise AppError("FORBIDDEN", "This media link is invalid or has expired.", 403)
    try:
        data = await storage.read(rel_path)
    except (FileNotFoundError, ValueError) as exc:
        raise not_found("Image") from exc
    return Response(content=data, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=3600"})
