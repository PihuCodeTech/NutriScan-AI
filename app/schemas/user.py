from __future__ import annotations

from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.common import ActivityLevel, DietType, Goal, Nutrients, Sex


class ProfileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    age: int | None = None
    sex: Sex | None = None
    height_cm: float | None = None
    weight_kg: float | None = None
    activity_level: ActivityLevel | None = None
    goal: Goal | None = None
    diet_type: DietType | None = None
    allergies: list[str] = []
    conditions: list[str] = []
    country: str = "IN"
    timezone: str = "Asia/Kolkata"


def _clean_list(values: list[str] | None) -> list[str] | None:
    if values is None:
        return None
    seen: list[str] = []
    for v in values:
        v = v.strip()
        if v and v.lower() not in {s.lower() for s in seen}:
            seen.append(v)
    return seen


class ProfileUpdate(BaseModel):
    """All fields optional; only the fields sent are changed."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "age": 20,
                "sex": "male",
                "height_cm": 175,
                "weight_kg": 70,
                "activity_level": "moderate",
                "goal": "maintain",
                "diet_type": "veg",
                "allergies": ["peanuts"],
                "conditions": [],
            }
        }
    )

    age: int | None = Field(None, ge=13, le=100)
    sex: Sex | None = None
    height_cm: float | None = Field(None, ge=80, le=250)
    weight_kg: float | None = Field(None, ge=20, le=350)
    activity_level: ActivityLevel | None = None
    goal: Goal | None = None
    diet_type: DietType | None = None
    allergies: list[str] | None = Field(None, max_length=20)
    conditions: list[str] | None = Field(None, max_length=20)
    country: str | None = Field(None, min_length=2, max_length=2)
    timezone: str | None = Field(None, max_length=64)

    @field_validator("allergies", "conditions")
    @classmethod
    def _lists(cls, v: list[str] | None) -> list[str] | None:
        if v is not None and any(len(s) > 60 for s in v):
            raise ValueError("each entry must be at most 60 characters")
        return _clean_list(v)

    @field_validator("country")
    @classmethod
    def _country(cls, v: str | None) -> str | None:
        return v.upper() if v else v

    @field_validator("timezone")
    @classmethod
    def _tz(cls, v: str | None) -> str | None:
        if v is None:
            return v
        try:
            ZoneInfo(v)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError("unknown IANA timezone, e.g. Asia/Kolkata") from exc
        return v


class UserOut(BaseModel):
    id: str
    email: str
    name: str
    profile: ProfileOut
    onboarding_complete: bool
    is_guest: bool = False


class TargetsOut(Nutrients):
    """Daily targets. Goal nutrients: calories, protein, carbs, fat, fibre. Limits: sat fat, sugar, sodium."""

    basis: Literal["profile", "default"]
    explanation: str
    bmr: float | None = None
    tdee: float | None = None
    goal_nutrients: list[str]
    limit_nutrients: list[str]
