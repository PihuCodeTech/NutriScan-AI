"""GET /metrics: Prometheus text format, for a scraper (Prometheus, Grafana Agent/Alloy, Better Stack, ...).

Outside /api/v1 and the JSON envelope on purpose: scrapers expect this path and format. Disabled (404) unless
METRICS_TOKEN is set, and then it needs `Authorization: Bearer <METRICS_TOKEN>`. The numbers hold no user
data, but they do reveal traffic and error levels, so they aren't public."""

from __future__ import annotations

import hmac

from fastapi import APIRouter, Request
from fastapi.responses import PlainTextResponse

from app.api.deps import SettingsDep
from app.core.errors import AppError, not_found
from app.core.metrics import metrics

router = APIRouter(include_in_schema=False)


@router.get("/metrics")
async def get_metrics(request: Request, settings: SettingsDep) -> PlainTextResponse:
    if not settings.METRICS_TOKEN:
        raise not_found()
    supplied = request.headers.get("authorization", "").removeprefix("Bearer ").strip()
    if not hmac.compare_digest(supplied.encode(), settings.METRICS_TOKEN.encode()):
        raise AppError("UNAUTHORIZED", "Missing or invalid metrics token.", 401)
    return PlainTextResponse(metrics.render(), media_type="text/plain; version=0.0.4; charset=utf-8")
