from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, File, Form, Query, Request, UploadFile
from fastapi.responses import StreamingResponse

from app.api.deps import DB, LLM, CurrentUser, SettingsDep, StorageDep
from app.api.v1.docs import AI, AUTH, errors
from app.core.rate_limit import ai_limit, limiter
from app.core.responses import ok
from app.schemas.chat import (
    ChatExchange,
    ChatSessionCreate,
    ChatSessionDetail,
    ChatSessionOut,
    ChatSessionRename,
    Suggestions,
)
from app.schemas.common import Envelope, Page
from app.services import scan_service
from app.services.chat import chat_service

router = APIRouter(prefix="/chat", tags=["chat"])

TextField = Annotated[str | None, Form(description="Required unless an image is attached; ≤ 2000 chars")]
ImageField = Annotated[UploadFile | None, File(description="Optional food photo (JPEG/PNG/WebP)")]


@router.get(
    "/suggestions",
    response_model=Envelope[Suggestions],
    summary="Starter prompts",
    description="4 starter prompts; pass `scan_id` for meal-specific ones.",
    responses=errors(*AUTH, "NOT_FOUND"),
)
async def get_suggestions(user: CurrentUser, db: DB, scan_id: Annotated[str | None, Query()] = None) -> dict:
    if scan_id:
        await scan_service.get_scan(db, user, scan_id)
    return ok({"suggestions": chat_service.suggestions(bool(scan_id))})


@router.post(
    "/sessions",
    status_code=201,
    response_model=Envelope[ChatSessionOut],
    summary="Create a chat session",
    description="Optionally link a scan (`scan_id`) so that meal is in the chatbot's context. Without a "
    "title, the first message's first ~6 words become the title.",
    responses=errors(*AUTH, "NOT_FOUND", "VALIDATION_ERROR"),
)
async def create_session(body: ChatSessionCreate, user: CurrentUser, db: DB) -> dict:
    session = await chat_service.create_session(db, user, title=body.title, scan_id=body.scan_id)
    return ok(chat_service.session_out(session), "CHAT_CREATED", "Chat created")


@router.get(
    "/sessions",
    response_model=Envelope[Page[ChatSessionOut]],
    summary="List chat sessions",
    description="Most recently active first, with a preview of the last message.",
    responses=errors(*AUTH, "VALIDATION_ERROR"),
)
async def list_sessions(
    user: CurrentUser,
    db: DB,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> dict:
    items, total = await chat_service.list_sessions(db, user, page=page, page_size=page_size)
    return ok({"items": items, "page": page, "page_size": page_size, "total": total})


@router.get(
    "/sessions/{session_id}",
    response_model=Envelope[ChatSessionDetail],
    summary="Get a chat session with messages",
    description="Messages oldest first. Assistant messages include a concise `tool_calls` trace.",
    responses=errors(*AUTH, "NOT_FOUND"),
)
async def get_session(session_id: str, user: CurrentUser, db: DB, storage: StorageDep) -> dict:
    session = await chat_service.get_session(db, user, session_id)
    messages = await chat_service.session_messages(db, session)
    preview = chat_service.preview(messages[-1]) if messages else None
    return ok(
        {
            "session": chat_service.session_out(session, preview),
            "messages": [chat_service.message_out(m, storage) for m in messages],
        }
    )


@router.patch(
    "/sessions/{session_id}",
    response_model=Envelope[ChatSessionOut],
    summary="Rename a chat session",
    description="Set a new title (1–120 characters).",
    responses=errors(*AUTH, "NOT_FOUND", "VALIDATION_ERROR"),
)
async def rename_session(session_id: str, body: ChatSessionRename, user: CurrentUser, db: DB) -> dict:
    session = await chat_service.get_session(db, user, session_id)
    session = await chat_service.rename_session(db, session, body.title)
    return ok(chat_service.session_out(session), "OK", "Chat renamed")


@router.delete(
    "/sessions/{session_id}",
    response_model=Envelope[None],
    summary="Delete a chat session",
    description="Deletes the session, its messages and any photos sent in it.",
    responses=errors(*AUTH, "NOT_FOUND"),
)
async def delete_session(session_id: str, user: CurrentUser, db: DB, storage: StorageDep) -> dict:
    session = await chat_service.get_session(db, user, session_id)
    await chat_service.delete_session(db, session, storage)
    return ok(None, "DELETED", "Chat deleted")


@router.post(
    "/sessions/{session_id}/messages",
    status_code=201,
    response_model=Envelope[ChatExchange],
    summary="Send a message",
    description="Multipart: `text` and/or `image`. Runs the Gemini tool loop (reads intake/scans/profile, can "
    "log meals when asked) and returns both the saved user message and the assistant reply.",
    responses=errors(*AUTH, "NOT_FOUND", "EMPTY_MESSAGE", "INVALID_IMAGE", "FILE_TOO_LARGE", "VALIDATION_ERROR", *AI),
)
@limiter.limit(ai_limit)
async def send_message(
    request: Request,
    session_id: str,
    user: CurrentUser,
    db: DB,
    llm: LLM,
    storage: StorageDep,
    settings: SettingsDep,
    text: TextField = None,
    image: ImageField = None,
) -> dict:
    session = await chat_service.get_session(db, user, session_id)
    user_msg, image_bytes = await chat_service.add_user_message(
        db, session, text=text, image=image, storage=storage, settings=settings
    )
    assistant = await chat_service.reply(
        db, user, session, current=user_msg, current_image=image_bytes, llm=llm, storage=storage, settings=settings
    )
    data = {
        "user_message": chat_service.message_out(user_msg, storage),
        "assistant_message": chat_service.message_out(assistant, storage),
    }
    return ok(data, "MESSAGE_CREATED", "Message sent")


@router.post(
    "/sessions/{session_id}/messages/stream",
    summary="Send a message (SSE stream)",
    description=(
        "Same multipart input. Responds with `text/event-stream` events: `user_message` (ChatMessage), "
        "`tool` ({name, summary}) per tool call, `delta` ({text}) chunks, then `done` (final saved ChatMessage) "
        "or `error` ({code, message}). Validation errors (empty message, bad image, unknown session) are "
        "returned as normal JSON envelopes before the stream starts. Use fetch + ReadableStream (EventSource "
        "can't POST multipart)."
    ),
    response_class=StreamingResponse,
    responses={
        200: {
            "description": "SSE stream",
            "content": {
                "text/event-stream": {
                    "example": 'event: user_message\ndata: {"id": "…", "role": "user", "content": "How did I do?"}\n\n'
                    'event: tool\ndata: {"name": "get_daily_intake", "summary": "Checking today\'s intake…"}\n\n'
                    'event: delta\ndata: {"text": "So far today "}\n\n'
                    'event: done\ndata: {"id": "…", "role": "assistant", "content": "So far today …"}\n\n'
                }
            },
        },
        **errors(*AUTH, "NOT_FOUND", "EMPTY_MESSAGE", "INVALID_IMAGE", "FILE_TOO_LARGE", "RATE_LIMITED"),
    },
)
@limiter.limit(ai_limit)
async def send_message_stream(
    request: Request,
    session_id: str,
    user: CurrentUser,
    db: DB,
    llm: LLM,
    storage: StorageDep,
    settings: SettingsDep,
    text: TextField = None,
    image: ImageField = None,
) -> StreamingResponse:
    session = await chat_service.get_session(db, user, session_id)
    user_msg, image_bytes = await chat_service.add_user_message(
        db, session, text=text, image=image, storage=storage, settings=settings
    )
    generator = chat_service.stream_reply(
        user_id=user.id,
        session_id=session.id,
        current_id=user_msg.id,
        current_image=image_bytes,
        llm=llm,
        storage=storage,
        settings=settings,
    )
    return StreamingResponse(
        generator,
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
