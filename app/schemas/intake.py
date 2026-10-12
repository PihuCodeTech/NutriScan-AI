from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import NUTRIENT_EXAMPLE, MealType, Nutrients
from app.schemas.scan import FoodItem, Health

IntakeSource = Literal["scan", "description", "manual", "chat"]
HealthStatus = Literal["on_track", "over", "under", "no_data"]


class IntakeEntryOut(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "id": "9a8b7c6d-1111-4222-8333-444455556666",
                "source": "scan",
                "scan_id": "6f1c2d5e-3a4b-4c8d-9e0f-1a2b3c4d5e6f",
                "name": "Rajma Chawal Plate",
                "meal_type": "lunch",
                "eaten_at": "2026-09-28T07:35:00Z",
                "items": [],
                "totals": NUTRIENT_EXAMPLE,
            }
        }
    )

    id: str
    source: IntakeSource
    scan_id: str | None
    name: str
    meal_type: MealType
    eaten_at: datetime
    is_street_food: bool = False
    is_home_cooked: bool = False
    items: list[FoodItem]
    totals: Nutrients


class DescribeIn(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={"example": {"text": "2 roti, dal and a glass of lassi", "meal_type": "dinner", "log": False}}
    )

    text: str = Field(min_length=2, max_length=500)
    meal_type: MealType | None = None
    log: bool = False


class DescribeOut(BaseModel):
    meal_name: str | None
    items: list[FoodItem]
    totals: Nutrients
    health: Health
    intake_entry: IntakeEntryOut | None = None


class ManualItemIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    quantity_g: float | None = Field(None, gt=0, le=5000, description="Optional; omit when only the numbers are known")
    serving_description: str | None = Field(None, max_length=200, examples=["1 plate"])
    nutrients: Nutrients


class ManualIntakeIn(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "name": "Evening snack",
                "meal_type": "snack",
                "items": [
                    {
                        "name": "Banana",
                        "quantity_g": 120,
                        "nutrients": {
                            "calories": 107,
                            "protein_g": 1.3,
                            "carbohydrates_g": 27.4,
                            "fat_g": 0.4,
                            "saturated_fat_g": 0.1,
                            "fiber_g": 3.1,
                            "sugar_g": 14.7,
                            "sodium_mg": 1,
                        },
                    }
                ],
            }
        }
    )

    name: str = Field(min_length=1, max_length=120)
    meal_type: MealType
    eaten_at: datetime | None = None
    is_street_food: bool = False
    is_home_cooked: bool = False
    items: list[ManualItemIn] = Field(min_length=1, max_length=30)


class StatusFlag(BaseModel):
    nutrient: str
    level: Literal["high", "low"]
    percent: int
    message: str


class DailyIntakeOut(BaseModel):
    date: date
    health_status: HealthStatus
    entries: list[IntakeEntryOut]
    totals: Nutrients
    targets: Nutrients
    remaining: dict[str, float]
    percent_of_target: dict[str, int]
    status_flags: list[StatusFlag]


class DaySummary(BaseModel):
    date: date
    totals: Nutrients
    calorie_percent: int
    entries: int


class TopFood(BaseModel):
    name: str
    count: int


class IntakeSummaryOut(BaseModel):
    days: list[DaySummary]
    averages: Nutrients
    days_logged: int
    streak_days_logged: int
    street_free_streak_days: int
    street_food_count: int
    home_cooked_count: int
    top_foods: list[TopFood]
