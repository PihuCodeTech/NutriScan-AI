from __future__ import annotations

from fastapi import APIRouter, Request

from app.api.deps import DB
from app.api.v1.docs import errors
from app.core.rate_limit import limiter
from app.core.responses import ok
from app.core.security import create_access_token
from app.schemas.auth import LoginIn, RegisterIn, TokenOut
from app.schemas.common import Envelope
from app.services import user_service

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post(
    "/register",
    status_code=201,
    response_model=Envelope[TokenOut],
    summary="Create an account",
    description="Registers a user (email is lower-cased) and returns a 7-day bearer token.",
    responses=errors("EMAIL_TAKEN", "VALIDATION_ERROR"),
)
async def register(body: RegisterIn, db: DB) -> dict:
    user = await user_service.register(db, email=body.email, password=body.password, name=body.name)
    data = {"access_token": create_access_token(user.id), "token_type": "bearer", "user": user_service.user_out(user)}
    return ok(data, "REGISTERED", "Account created")


@router.post(
    "/login",
    response_model=Envelope[TokenOut],
    summary="Log in",
    description="Exchange email + password for a bearer token.",
    responses=errors("INVALID_CREDENTIALS", "VALIDATION_ERROR"),
)
async def login(body: LoginIn, db: DB) -> dict:
    user = await user_service.authenticate(db, email=body.email, password=body.password)
    data = {"access_token": create_access_token(user.id), "token_type": "bearer", "user": user_service.user_out(user)}
    return ok(data, "LOGGED_IN", "Logged in")


@router.post(
    "/guest",
    status_code=201,
    response_model=Envelope[TokenOut],
    summary="Start a guest session",
    description="Creates a throw-away guest account (`user.is_guest = true`) and returns a 7-day bearer token, so "
    "people who don't sign up still get real AI scans, chat and suggestions. Limited to 30 per hour per IP.",
    responses=errors("RATE_LIMITED"),
)
@limiter.limit("30/hour")
async def guest(request: Request, db: DB) -> dict:
    user = await user_service.create_guest(db)
    data = {"access_token": create_access_token(user.id), "token_type": "bearer", "user": user_service.user_out(user)}
    return ok(data, "GUEST_CREATED", "Guest session started")
