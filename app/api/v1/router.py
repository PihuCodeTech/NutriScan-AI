from __future__ import annotations

from fastapi import APIRouter

from app.api.v1 import auth, chat, health, insights, intake, media, meta, recipes, scans, users

api_router = APIRouter(prefix="/api/v1")
for module in (health, meta, auth, users, scans, intake, insights, chat, recipes, media):
    api_router.include_router(module.router)
