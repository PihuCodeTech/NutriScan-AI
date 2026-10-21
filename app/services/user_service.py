"""Accounts and profiles."""

from __future__ import annotations

import secrets
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.core.security import hash_password, verify_password
from app.db.models import Profile, User
from app.schemas.auth import GUEST_EMAIL_DOMAIN
from app.schemas.user import ProfileOut, ProfileUpdate
from app.services.health_engine import GOAL_NUTRIENTS, LIMIT_NUTRIENTS, compute_targets


async def register(db: AsyncSession, *, email: str, password: str, name: str) -> User:
    """Create a user (+ empty profile). Raises EMAIL_TAKEN."""
    email = email.strip().lower()
    existing = await db.scalar(select(User.id).where(User.email == email))
    if existing:
        raise AppError("EMAIL_TAKEN", "An account with this email already exists.", 409)
    user = User(email=email, password_hash=hash_password(password), name=name)
    user.profile = Profile(allergies=[], conditions=[])
    db.add(user)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise AppError("EMAIL_TAKEN", "An account with this email already exists.", 409) from exc
    await db.refresh(user, attribute_names=["profile"])
    return user


_DUMMY_HASH = hash_password(secrets.token_urlsafe(16))


def is_guest(user: User) -> bool:
    return user.email.endswith("@" + GUEST_EMAIL_DOMAIN)


async def create_guest(db: AsyncSession) -> User:
    """A real (server-side) account for someone who doesn't want to sign up, so every AI feature still runs
    through Gemini. Its password is random and never shown: the account lives only as long as the token."""
    email = f"guest-{uuid.uuid4().hex[:12]}@{GUEST_EMAIL_DOMAIN}"
    return await register(db, email=email, password=secrets.token_urlsafe(24), name="Guest")


async def authenticate(db: AsyncSession, *, email: str, password: str) -> User:
    """Return the user for valid credentials, else INVALID_CREDENTIALS."""
    user = await db.scalar(select(User).where(User.email == email.strip().lower()))
    if user is None:
        verify_password(password, _DUMMY_HASH)  # same bcrypt cost, so timing doesn't reveal unknown emails
        raise AppError("INVALID_CREDENTIALS", "Incorrect email or password.", 401)
    if not verify_password(password, user.password_hash):
        raise AppError("INVALID_CREDENTIALS", "Incorrect email or password.", 401)
    return user


async def ensure_profile(db: AsyncSession, user: User) -> Profile:
    if user.profile is None:
        user.profile = Profile(allergies=[], conditions=[])
        await db.flush()
    return user.profile


async def update_profile(db: AsyncSession, user: User, data: ProfileUpdate) -> User:
    """Partial update: only fields present in the request body are changed."""
    profile = await ensure_profile(db, user)
    for key, value in data.model_dump(exclude_unset=True).items():
        if key in {"allergies", "conditions"} and value is None:
            value = []
        if key in {"country", "timezone"} and value is None:
            continue  # these have defaults and are not nullable
        setattr(profile, key, value)
    await db.commit()
    await db.refresh(user, attribute_names=["profile"])
    return user


def user_out(user: User) -> dict[str, Any]:
    profile = user.profile
    return {
        "id": user.id,
        "email": user.email,
        "name": user.name,
        "profile": ProfileOut.model_validate(profile).model_dump() if profile else ProfileOut().model_dump(),
        "onboarding_complete": bool(profile and profile.onboarding_complete),
        "is_guest": is_guest(user),
    }


def targets_out(profile: Profile | None) -> dict[str, Any]:
    t = compute_targets(profile)
    return {
        **t.nutrients,
        "basis": t.basis,
        "explanation": t.explanation(),
        "bmr": t.bmr,
        "tdee": t.tdee,
        "goal_nutrients": list(GOAL_NUTRIENTS),
        "limit_nutrients": list(LIMIT_NUTRIENTS),
    }


def user_context(user: User) -> str:
    """Compact user context for Gemini prompts ('unknown' when missing)."""
    p = user.profile

    def val(v: Any) -> str:
        if v is None or v == []:
            return "unknown" if not isinstance(v, list) else "none"
        return ", ".join(v) if isinstance(v, list) else str(v)

    return "\n".join(
        [
            f"Country: {val(p.country if p else None)}",
            f"Diet type: {val(p.diet_type if p else None)}",
            f"Allergies: {val(p.allergies if p else [])}",
            f"Goal: {val(p.goal if p else None)}",
        ]
    )
