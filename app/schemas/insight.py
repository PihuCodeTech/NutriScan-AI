from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict

from app.core.config import DISCLAIMER
from app.schemas.intake import HealthStatus


class DailyInsightOut(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "date": "2026-09-28",
                "headline": "Solid start — protein needs a boost",
                "summary": "You're at 48% of your calories with lunch done. Protein is a bit low so far.",
                "tips": [
                    "Add a katori of curd or sprouts to dinner.",
                    "Swap the evening samosa for roasted chana.",
                    "Drink a glass of water before each meal.",
                ],
                "health_status": "on_track",
                "disclaimer": DISCLAIMER,
            }
        }
    )

    date: date
    headline: str
    summary: str
    tips: list[str]
    health_status: HealthStatus
    disclaimer: str = DISCLAIMER
