"""Chat sessions and messages, history building and the tool loop (flow B), plus SSE streaming."""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from fastapi import UploadFile
from fastapi.encoders import jsonable_encoder
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import AppError, not_found
from app.core.metrics import metrics
from app.db.base import utcnow
from app.db.models import ChatMessage, ChatSession, User
from app.db.session import get_sessionmaker
from app.schemas.chat import ChatMessageOut
from app.services import images, scan_service
from app.services.chat import tools
from app.services.chat.context import build_chat_system
from app.services.llm.gemini_client import LLMClient
from app.services.llm.schemas import ChatHistoryItem, ChatTurn, FunctionResult
from app.services.storage import Storage

logger = logging.getLogger(__name__)

DEFAULT_TITLE = "New chat"
MAX_TEXT_CHARS = 2000
TITLE_WORDS = 6
PREVIEW_CHARS = 120
PHOTO_MARKER = "[user shared a photo]"
EMPTY_ANSWER = "Sorry, I couldn't come up with an answer just now. Could you rephrase that?"


# ---------------------------------------------------------------------- serialisers


def message_out(msg: ChatMessage, storage: Storage) -> dict[str, Any]:
    return {
        "id": msg.id,
        "role": msg.role,
        "content": msg.content,
        "image_url": storage.url(msg.image_path) if msg.image_path else None,
        "tool_calls": (
            [{"name": t["name"], "args": t.get("args", {}), "summary": t.get("summary", "")} for t in msg.tool_calls]
            if msg.role == "assistant" and msg.tool_calls
            else None
        ),
        "created_at": msg.created_at,
    }


def session_out(session: ChatSession, preview: str | None = None) -> dict[str, Any]:
    return {
        "id": session.id,
        "title": session.title,
        "scan_id": session.scan_id,
        "last_message_preview": preview,
        "created_at": session.created_at,
        "updated_at": session.updated_at,
    }


def preview(msg: ChatMessage | None) -> str | None:
    if msg is None:
        return None
    text = msg.content.strip().replace("\n", " ")
    if not text and msg.image_path:
        return "📷 Photo"
    return text[:PREVIEW_CHARS] + ("…" if len(text) > PREVIEW_CHARS else "")


# ---------------------------------------------------------------------- sessions


async def get_session(db: AsyncSession, user: User, session_id: str) -> ChatSession:
    session = await db.scalar(select(ChatSession).where(ChatSession.id == session_id, ChatSession.user_id == user.id))
    if session is None:
        raise not_found("Chat session")
    return session


async def create_session(db: AsyncSession, user: User, *, title: str | None, scan_id: str | None) -> ChatSession:
    if scan_id:
        await scan_service.get_scan(db, user, scan_id)  # 404 unless it's the user's scan
    session = ChatSession(user_id=user.id, title=(title or "").strip() or DEFAULT_TITLE, scan_id=scan_id)
    db.add(session)
    await db.commit()
    return session


async def list_sessions(db: AsyncSession, user: User, *, page: int, page_size: int) -> tuple[list[dict[str, Any]], int]:
    total = await db.scalar(select(func.count()).select_from(ChatSession).where(ChatSession.user_id == user.id)) or 0
    sessions = list(
        await db.scalars(
            select(ChatSession)
            .where(ChatSession.user_id == user.id)
            .order_by(ChatSession.updated_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    )
    out = []
    for s in sessions:
        last = await db.scalar(
            select(ChatMessage).where(ChatMessage.session_id == s.id).order_by(ChatMessage.created_at.desc()).limit(1)
        )
        out.append(session_out(s, preview(last)))
    return out, total


async def session_messages(db: AsyncSession, session: ChatSession) -> list[ChatMessage]:
    rows = await db.scalars(
        select(ChatMessage).where(ChatMessage.session_id == session.id).order_by(ChatMessage.created_at)
    )
    return list(rows)


async def rename_session(db: AsyncSession, session: ChatSession, title: str) -> ChatSession:
    session.title = title.strip()
    await db.commit()
    return session


async def delete_session(db: AsyncSession, session: ChatSession, storage: Storage) -> None:
    paths = [m.image_path for m in await session_messages(db, session) if m.image_path]
    await db.execute(delete(ChatMessage).where(ChatMessage.session_id == session.id))
    await db.delete(session)
    await db.commit()
    for p in paths:
        await storage.delete(p)


def suggestions(has_scan: bool) -> list[str]:
    if has_scan:
        return [
            "How can I make this meal healthier?",
            "Is this enough protein for me?",
            "What should I eat later today to balance this meal?",
            "Is this meal good for muscle gain?",
        ]
    return [
        "Cheap high-protein foods in a hostel?",
        "What should I eat at night when studying?",
        "How did I do today?",
        "Healthy options at a college canteen?",
    ]


# ---------------------------------------------------------------------- messages


def _auto_title(text: str) -> str:
    words = text.split()
    title = " ".join(words[:TITLE_WORDS])
    if len(words) > TITLE_WORDS:
        title += "…"
    return title[:120] or DEFAULT_TITLE


async def add_user_message(
    db: AsyncSession,
    session: ChatSession,
    *,
    text: str | None,
    image: UploadFile | None,
    storage: Storage,
    settings: Settings,
) -> tuple[ChatMessage, bytes | None]:
    """Validate and persist the user's message (+ image). Returns the message and normalised image bytes."""
    text = (text or "").strip()
    has_image = image is not None and bool(image.filename or image.size)
    if not text and not has_image:
        raise AppError("EMPTY_MESSAGE", "Type a message or attach a photo.", 400)
    if len(text) > MAX_TEXT_CHARS:
        raise AppError(
            "VALIDATION_ERROR",
            f"Message is too long (max {MAX_TEXT_CHARS} characters).",
            422,
            [{"loc": ["body", "text"], "msg": f"at most {MAX_TEXT_CHARS} characters", "type": "string_too_long"}],
        )
    image_bytes: bytes | None = None
    image_path: str | None = None
    if has_image and image is not None:
        normalized = await images.validate_and_normalise(image, settings.max_upload_bytes)
        image_bytes = normalized.data
        image_path = await storage.save(image_bytes, "jpg")

    had_messages = await db.scalar(
        select(func.count()).select_from(ChatMessage).where(ChatMessage.session_id == session.id)
    )
    msg = ChatMessage(session_id=session.id, role="user", content=text, image_path=image_path)
    db.add(msg)
    if not had_messages and session.title == DEFAULT_TITLE:
        session.title = _auto_title(text) if text else "Food photo"
    session.updated_at = utcnow()
    try:
        await db.commit()
    except BaseException:
        if image_path:  # no row references the photo, so nothing else would ever delete it
            await storage.delete(image_path)
        raise
    return msg, image_bytes


async def build_history(
    db: AsyncSession, session: ChatSession, *, current: ChatMessage, current_image: bytes | None, limit: int
) -> list[ChatHistoryItem]:
    """Last `limit` messages (including the current one). Only the current message carries image bytes."""
    rows = list(
        await db.scalars(
            select(ChatMessage)
            .where(ChatMessage.session_id == session.id)
            .order_by(ChatMessage.created_at.desc())
            .limit(max(limit, 1))
        )
    )
    rows.reverse()
    history: list[ChatHistoryItem] = []
    for m in rows:
        if m.role == "user":
            if m.id == current.id:
                history.append(
                    ChatHistoryItem(
                        role="user",
                        text=m.content or ("What's in this photo?" if current_image else ""),
                        image=current_image,
                        image_mime="image/jpeg" if current_image else None,
                    )
                )
            else:
                text = f"{PHOTO_MARKER} {m.content}".strip() if m.image_path else m.content
                history.append(ChatHistoryItem(role="user", text=text))
        elif m.content:
            history.append(ChatHistoryItem(role="model", text=m.content))
    return history


@dataclass
class TurnState:
    traces: list[dict[str, Any]] = field(default_factory=list)
    texts: list[str] = field(default_factory=list)

    @property
    def content(self) -> str:
        return "\n\n".join(t.strip() for t in self.texts if t and t.strip()) or EMPTY_ANSWER


async def _run_tools(turn: ChatTurn, history: list[ChatHistoryItem], ctx: tools.ToolContext, state: TurnState) -> None:
    history.append(ChatHistoryItem(role="model", text=turn.text, function_calls=turn.function_calls, raw=turn.raw))
    results: list[FunctionResult] = []
    for fc in turn.function_calls:
        response, summary, ok = await tools.execute(fc.name, fc.args, ctx)
        state.traces.append({"name": fc.name, "args": fc.args, "summary": summary, "ok": ok, "result": response})
        results.append(FunctionResult(name=fc.name, response=response, id=fc.id))
    history.append(ChatHistoryItem(role="tool", function_results=results))


async def _save_assistant(db: AsyncSession, session: ChatSession, state: TurnState, llm: LLMClient) -> ChatMessage:
    msg = ChatMessage(
        session_id=session.id,
        role="assistant",
        content=state.content,
        tool_calls=jsonable_encoder(state.traces) if state.traces else None,
        ai_model=llm.last_model_used,
    )
    db.add(msg)
    session.updated_at = utcnow()
    await db.commit()
    return msg


async def reply(
    db: AsyncSession,
    user: User,
    session: ChatSession,
    *,
    current: ChatMessage,
    current_image: bytes | None,
    llm: LLMClient,
    storage: Storage,
    settings: Settings,
) -> ChatMessage:
    """Non-streaming turn: tool loop (≤ CHAT_MAX_TOOL_ROUNDS), then save the assistant message."""
    system = await build_chat_system(db, user, session)
    history = await build_history(
        db, session, current=current, current_image=current_image, limit=settings.CHAT_HISTORY_TURNS
    )
    ctx = tools.ToolContext(db=db, user=user, llm=llm, storage=storage)
    state = TurnState()
    for _ in range(settings.CHAT_MAX_TOOL_ROUNDS):
        turn = await llm.chat_turn(system=system, history=history, tools=tools.TOOL_SPECS)
        if turn.text:
            state.texts.append(turn.text)
        if not turn.function_calls:
            break
        await _run_tools(turn, history, ctx, state)
    else:
        final = await llm.chat_turn(system=system, history=history, tools=[])
        if final.text:
            state.texts.append(final.text)
    return await _save_assistant(db, session, state, llm)


def sse(event: str, data: Any) -> str:
    return f"event: {event}\ndata: {json.dumps(jsonable_encoder(data), ensure_ascii=False)}\n\n"


async def stream_reply(
    *,
    user_id: str,
    session_id: str,
    current_id: str,
    current_image: bytes | None,
    llm: LLMClient,
    storage: Storage,
    settings: Settings,
) -> AsyncIterator[str]:
    """SSE: user_message → tool* → delta* → done (or error). Uses its own DB session."""
    async with get_sessionmaker()() as db:
        user = await db.get(User, user_id)
        session = await db.get(ChatSession, session_id)
        current = await db.get(ChatMessage, current_id)
        if user is None or session is None or current is None:
            yield sse("error", {"code": "NOT_FOUND", "message": "Chat session not found."})
            return
        yield sse("user_message", ChatMessageOut.model_validate(message_out(current, storage)).model_dump(mode="json"))
        try:
            system = await build_chat_system(db, user, session)
            history = await build_history(
                db, session, current=current, current_image=current_image, limit=settings.CHAT_HISTORY_TURNS
            )
            ctx = tools.ToolContext(db=db, user=user, llm=llm, storage=storage)
            state = TurnState()
            rounds = 0
            while True:
                use_tools = rounds < settings.CHAT_MAX_TOOL_ROUNDS
                turn: ChatTurn | None = None
                round_text: list[str] = []
                async for chunk in llm.chat_stream(
                    system=system, history=history, tools=tools.TOOL_SPECS if use_tools else None
                ):
                    if chunk.text:
                        round_text.append(chunk.text)
                        yield sse("delta", {"text": chunk.text})
                    if chunk.final is not None:
                        turn = chunk.final
                if round_text:
                    state.texts.append("".join(round_text))
                if turn is None or not turn.function_calls or not use_tools:
                    break
                for fc in turn.function_calls:
                    yield sse("tool", {"name": fc.name, "summary": tools.PROGRESS_LABELS.get(fc.name, "Working…")})
                await _run_tools(turn, history, ctx, state)
                rounds += 1
            msg = await _save_assistant(db, session, state, llm)
            metrics.inc("events_total", event="MESSAGE_STREAMED")
            yield sse("done", ChatMessageOut.model_validate(message_out(msg, storage)).model_dump(mode="json"))
        except AppError as exc:
            await db.rollback()
            # Streams answer 200 and report errors in-band, so count them here like the error envelope does.
            metrics.inc("app_errors_total", code=exc.code)
            error = {"code": exc.code, "message": exc.message}
            if exc.details:
                error["details"] = exc.details  # e.g. {"reason": "auth"} for a rejected Gemini key
            yield sse("error", error)
        except Exception:
            metrics.inc("unhandled_exceptions_total", where="chat_stream")
            logger.exception("chat stream failed")
            await db.rollback()
            yield sse("error", {"code": "INTERNAL_ERROR", "message": "Something went wrong on our side."})
