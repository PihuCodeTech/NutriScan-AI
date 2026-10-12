from __future__ import annotations

from pydantic import BaseModel


class NutrientMeta(BaseModel):
    key: str
    label: str
    unit: str
    kind: str  # "goal" or "limit"
    decimals: int


class HealthLabelMeta(BaseModel):
    label: str
    color: str
    min_score: int
    max_score: int
    display: str


class OptionMeta(BaseModel):
    value: str
    label: str


class MetaOut(BaseModel):
    nutrients: list[NutrientMeta]
    meal_types: list[OptionMeta]
    diet_types: list[OptionMeta]
    activity_levels: list[OptionMeta]
    goals: list[OptionMeta]
    sexes: list[OptionMeta]
    health_labels: list[HealthLabelMeta]
    meal_shares: dict[str, float]
    disclaimer: str
    max_upload_mb: float
    accepted_image_types: list[str]


class HealthOut(BaseModel):
    status: str
    db: str
    classifier: str
    gemini: str
    version: str
