from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import DB, CurrentUser
from app.api.v1.docs import AUTH, errors
from app.core.responses import ok
from app.schemas.common import Envelope
from app.schemas.user import ProfileUpdate, TargetsOut, UserOut
from app.services import user_service

router = APIRouter(prefix="/users", tags=["users"])


@router.get(
    "/me",
    response_model=Envelope[UserOut],
    summary="Current user",
    description="The user, their profile and whether onboarding is complete "
    "(age, sex, height, weight, activity and goal all set).",
    responses=errors(*AUTH),
)
async def me(user: CurrentUser) -> dict:
    return ok(user_service.user_out(user))


@router.put(
    "/me/profile",
    response_model=Envelope[UserOut],
    summary="Update profile (partial)",
    description="Upsert the profile. All fields are optional; only the fields you send are changed. "
    "Send `null` to clear a field.",
    responses=errors(*AUTH, "VALIDATION_ERROR"),
)
async def update_profile(body: ProfileUpdate, user: CurrentUser, db: DB) -> dict:
    user = await user_service.update_profile(db, user, body)
    return ok(user_service.user_out(user), "PROFILE_UPDATED", "Profile updated")


@router.get(
    "/me/targets",
    response_model=Envelope[TargetsOut],
    summary="Daily nutrition targets",
    description="Computed daily targets (Nutrients shape) plus `basis` (`profile` or `default`) and a short "
    "explanation. Mifflin–St Jeor BMR × activity, goal-adjusted, never below max(1200, BMR).",
    responses=errors(*AUTH),
)
async def targets(user: CurrentUser) -> dict:
    return ok(user_service.targets_out(user.profile))
