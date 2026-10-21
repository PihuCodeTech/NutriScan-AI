from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.schemas.user import UserOut

# Throw-away accounts from POST /auth/guest live on this domain and are deleted after GUEST_RETENTION_DAYS,
# so nobody may register a real account on it.
GUEST_EMAIL_DOMAIN = "guest.nutriscan.app"
# bcrypt only uses the first 72 bytes of a password; longer ones would match on their prefix alone.
PASSWORD_MAX_BYTES = 72


class RegisterIn(BaseModel):
    email: EmailStr = Field(examples=["asha@example.com"])
    password: str = Field(
        min_length=8, max_length=128, description="8 characters to 72 bytes (UTF-8)", examples=["hostel-life-123"]
    )
    name: str = Field(min_length=1, max_length=100, examples=["Asha"])

    @field_validator("email")
    @classmethod
    def _not_guest_domain(cls, v: str) -> str:
        if v.rsplit("@", 1)[-1].lower() == GUEST_EMAIL_DOMAIN:
            raise ValueError("this email domain is reserved for guest sessions")
        return v

    @field_validator("password")
    @classmethod
    def _bcrypt_limit(cls, v: str) -> str:
        if len(v.encode("utf-8")) > PASSWORD_MAX_BYTES:
            raise ValueError(f"password must be at most {PASSWORD_MAX_BYTES} bytes")
        return v

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
