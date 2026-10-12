from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.schemas.user import UserOut


class RegisterIn(BaseModel):
    email: EmailStr = Field(examples=["asha@example.com"])
    password: str = Field(min_length=8, max_length=128, examples=["hostel-life-123"])
    name: str = Field(min_length=1, max_length=100, examples=["Asha"])

    @field_validator("name")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("name must not be blank")
        return v


class LoginIn(BaseModel):
    email: EmailStr = Field(examples=["asha@example.com"])
    password: str = Field(min_length=1, max_length=128, examples=["hostel-life-123"])


class TokenOut(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    user: UserOut
