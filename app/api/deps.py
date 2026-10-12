"""Shared FastAPI dependencies: DB session, current user and the AI services (real or mock)."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.errors import unauthorized
from app.core.logging import user_id_var
from app.core.security import decode_access_token
from app.db.models import User
from app.db.session import get_db
from app.services.classifier import Classifier, DisabledClassifier, HFClassifier, MockClassifier
from app.services.llm.gemini_client import GeminiClient, LLMClient
from app.services.llm.mock_client import MockGeminiClient
from app.services.storage import LocalStorage, Storage

_bearer = HTTPBearer(auto_error=False, description="JWT from /auth/login or /auth/register")


def build_llm(settings: Settings) -> LLMClient:
    """MOCK_AI=true → deterministic fixtures; otherwise the real Gemini client."""
    return MockGeminiClient() if settings.MOCK_AI else GeminiClient(settings)


def build_classifier(settings: Settings) -> Classifier:
    if not settings.CLASSIFIER_ENABLED:
        return DisabledClassifier(settings.CLASSIFIER_MODEL_ID)
    if settings.MOCK_AI:
        return MockClassifier(settings.CLASSIFIER_MODEL_ID, settings.CLASSIFIER_TOP_K)
    return HFClassifier(settings.CLASSIFIER_MODEL_ID, settings.CLASSIFIER_TOP_K)


def build_storage(settings: Settings) -> Storage:
    return LocalStorage(settings.STORAGE_DIR, settings.PUBLIC_BASE_URL, settings.JWT_SECRET, settings.MEDIA_URL_TTL_S)


def get_llm(request: Request) -> LLMClient:
    return request.app.state.llm


def get_classifier(request: Request) -> Classifier:
    return request.app.state.classifier


def get_storage(request: Request) -> Storage:
    return request.app.state.storage


async def get_current_user(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> User:
    """Resolve the bearer token to a user, else 401 UNAUTHORIZED."""
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise unauthorized()
    user_id = decode_access_token(credentials.credentials)
    if user_id is None:
        raise unauthorized("Your session has expired or the token is invalid. Please log in again.")
    user = await db.get(User, user_id)
    if user is None:
        raise unauthorized()
    request.state.user_id = user.id
    user_id_var.set(user.id)
    return user


DB = Annotated[AsyncSession, Depends(get_db)]
CurrentUser = Annotated[User, Depends(get_current_user)]
LLM = Annotated[LLMClient, Depends(get_llm)]
ClassifierDep = Annotated[Classifier, Depends(get_classifier)]
StorageDep = Annotated[Storage, Depends(get_storage)]
SettingsDep = Annotated[Settings, Depends(get_settings)]
