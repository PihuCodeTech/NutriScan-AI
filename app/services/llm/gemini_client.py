"""Gemini access. This is the ONLY module that imports `google.genai`.

Supports the Gemini Developer API (AI Studio key) and Vertex AI express mode (`GEMINI_USE_VERTEX=true`).
Reliability: per-call timeout; on timeout/429/5xx retry once after ~1.5 s, then the fallback model once,
then `AI_UNAVAILABLE`. Structured output that fails validation is re-asked once, then `AI_BAD_RESPONSE`.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any, Protocol, TypeVar

from google import genai
from google.genai import errors as genai_errors
from google.genai import types
from pydantic import BaseModel, ValidationError

from app.core.config import Settings
from app.core.errors import AppError, ai_unavailable
from app.core.metrics import metrics
from app.services.llm import prompts

# Re-exported so scripts/smoke_gemini.py and tests can keep importing them from this module.
from app.services.llm.retry import (  # noqa: F401
    RETRY_DELAY_S,
    describe_error,
    is_auth_error,
    is_network_error,
    is_not_found,
    should_cool_down,
)
from app.services.llm.retry import classify as _classify
from app.services.llm.retry import describe as _describe
from app.services.llm.retry import unavailable as _unavailable
from app.services.llm.schemas import (
    ChatHistoryItem,
    ChatTurn,
    FoodAnalysisLLM,
    FunctionCall,
    InsightLLM,
    RecipesLLM,
    StreamChunk,
    TipsLLM,
    ToolSpec,
)

logger = logging.getLogger(__name__)

T = TypeVar("T")
M = TypeVar("M", bound=BaseModel)

STRUCTURED_TEMPERATURE = 0.2
CHAT_TEMPERATURE = 0.6


class LLMClient(Protocol):
    """Implemented by `GeminiClient` and `MockGeminiClient`."""

    async def analyze_food_image(
        self, image: bytes, mime: str, *, hints: list[dict[str, Any]], user_ctx: str, description: str | None
    ) -> FoodAnalysisLLM: ...

    async def estimate_from_text(self, text: str, *, user_ctx: str) -> FoodAnalysisLLM: ...

    async def generate_tips(
        self, *, items: list[dict[str, Any]], totals: dict[str, Any], flags: list[dict[str, Any]], user_ctx: str
    ) -> TipsLLM: ...

    async def daily_insight(self, *, day_summary: dict[str, Any], user_ctx: str) -> InsightLLM: ...

    async def suggest_recipes(
        self, *, ingredients: list[str], kitchen: str, count: int, user_ctx: str, note: str | None
    ) -> RecipesLLM: ...

    async def chat_turn(self, *, system: str, history: list[ChatHistoryItem], tools: list[ToolSpec]) -> ChatTurn: ...

    def chat_stream(
        self, *, system: str, history: list[ChatHistoryItem], tools: list[ToolSpec] | None = None
    ) -> AsyncIterator[StreamChunk]: ...

    @property
    def last_model_used(self) -> str: ...


class _BadResponse(Exception):
    pass


def _strip_fences(text: str) -> str:
    text = text.strip()
    match = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.DOTALL)
    return match.group(1) if match else text


def _response_text(resp: Any) -> str:
    """Concatenate non-thought text parts (avoids SDK warnings when function calls are present)."""
    try:
        parts = resp.candidates[0].content.parts or []
    except (AttributeError, IndexError, TypeError):
        return ""
    return "".join(p.text for p in parts if getattr(p, "text", None) and not getattr(p, "thought", False))


def _log_usage(resp: Any, *, op: str, model: str, started: float) -> None:
    usage = getattr(resp, "usage_metadata", None)
    elapsed = time.perf_counter() - started
    prompt_tokens = getattr(usage, "prompt_token_count", None)
    output_tokens = getattr(usage, "candidates_token_count", None)
    logger.info(
        "gemini call",
        extra={
            "op": op,
            "model": model,
            "latency_ms": round(elapsed * 1000),
            "prompt_tokens": prompt_tokens,
            "output_tokens": output_tokens,
            "total_tokens": getattr(usage, "total_token_count", None),
        },
    )
    _record_success(op, model, elapsed, prompt_tokens, output_tokens)


def _record_success(op: str, model: str, elapsed: float, prompt_tokens: Any, output_tokens: Any) -> None:
    metrics.inc("gemini_requests_total", op=op, model=model, outcome="ok")
    metrics.observe("gemini_request_duration_seconds", elapsed, op=op, model=model)
    if isinstance(prompt_tokens, int):
        metrics.inc("gemini_tokens_total", prompt_tokens, model=model, kind="prompt")
    if isinstance(output_tokens, int):
        metrics.inc("gemini_tokens_total", output_tokens, model=model, kind="output")


def _give_up(op: str, exc: BaseException | None) -> AppError:
    """The user-facing AI_UNAVAILABLE error for the last failure, counted by reason for the alert rules."""
    error = _unavailable(exc)
    reason = (error.details or {}).get("reason", "unavailable")
    metrics.inc("gemini_unavailable_total", op=op, reason=reason)
    return error


def make_sdk_client(api_key: str, use_vertex: bool, timeout_s: float) -> genai.Client:
    """Create a google-genai client for the Developer API or Vertex AI express mode."""
    http_options = types.HttpOptions(timeout=int(timeout_s * 1000))
    if use_vertex:
        return genai.Client(vertexai=True, api_key=api_key, http_options=http_options)
    return genai.Client(api_key=api_key, http_options=http_options)


class GeminiClient:
    """Real Gemini implementation of `LLMClient`."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._client: genai.Client | None = None
        self._last_model = settings.GEMINI_MODEL
        self._no_thinking: set[str] = set()  # models that rejected `thinking_level`
        self._cooldown_until: dict[str, float] = {}  # model → monotonic time until which it is tried last

    # ------------------------------------------------------------------ plumbing

    @property
    def last_model_used(self) -> str:
        return self._last_model

    def _sdk(self) -> genai.Client:
        if not self.settings.GEMINI_API_KEY:
            raise ai_unavailable(
                "The AI service is not configured: GEMINI_API_KEY is empty in the backend's .env file.",
                reason="not_configured",
            )
        if self._client is None:
            self._client = make_sdk_client(
                self.settings.GEMINI_API_KEY, self.settings.GEMINI_USE_VERTEX, self.settings.GEMINI_TIMEOUT_S
            )
        return self._client

    def _model_plan(self) -> list[tuple[str, float]]:
        """(model, delay-before-attempt): primary, primary again after a pause, then the fallback.

        Circuit breaker: if the primary failed moments ago (overloaded, timed out, quota), the fallback goes
        first and the primary is only a last resort, so one struggling model doesn't add 10-30 s to every
        request. The primary is tried first again once its cooldown ends."""
        primary, fallback = self.settings.GEMINI_MODEL, self.settings.GEMINI_FALLBACK_MODEL
        if not fallback or fallback == primary:
            return [(primary, 0.0), (primary, RETRY_DELAY_S)]
        if self._cooling(primary) and not self._cooling(fallback):
            return [(fallback, 0.0), (primary, 0.0)]
        return [(primary, 0.0), (primary, RETRY_DELAY_S), (fallback, 0.0)]

    def _cooling(self, model: str) -> bool:
        return time.monotonic() < self._cooldown_until.get(model, 0.0)

    def _note_failure(self, model: str, exc: BaseException) -> None:
        cooldown = self.settings.GEMINI_COOLDOWN_S
        if cooldown <= 0 or not should_cool_down(exc):
            return
        if not self._cooling(model):
            logger.warning(
                "gemini model cooling down; the other model goes first",
                extra={"model": model, "seconds": cooldown, "error": _describe(exc)},
            )
        self._cooldown_until[model] = time.monotonic() + cooldown

    def _note_success(self, model: str) -> None:
        self._last_model = model
        self._cooldown_until.pop(model, None)

    def _thinking(self, model: str) -> types.ThinkingConfig | None:
        """Low thinking keeps extraction and chat fast (Gemini 3 thinks a lot by default and can take > 30 s)."""
        level = self.settings.GEMINI_THINKING_LEVEL
        if not level or model in self._no_thinking:
            return None
        return types.ThinkingConfig(thinking_level=level.upper())

    def _rejects_thinking(self, exc: BaseException, model: str) -> bool:
        """True (and remembered) when a model refuses the thinking setting; the call is then retried without it."""
        if isinstance(exc, genai_errors.ClientError) and exc.code == 400 and "think" in (exc.message or "").lower():
            if model not in self._no_thinking:
                logger.info("model doesn't accept thinking_level; continuing without it", extra={"model": model})
            self._no_thinking.add(model)
            return True
        return False

    async def _generate(self, model: str, contents: Any, config: dict[str, Any]) -> Any:
        """generate_content with the configured thinking level, falling back to the model default if refused."""
        client = self._sdk()
        thinking = self._thinking(model)
        if thinking is not None:
            try:
                return await client.aio.models.generate_content(
                    model=model,
                    contents=contents,
                    config=types.GenerateContentConfig(**config, thinking_config=thinking),
                )
            except genai_errors.ClientError as exc:
                if not self._rejects_thinking(exc, model):
                    raise
        return await client.aio.models.generate_content(
            model=model, contents=contents, config=types.GenerateContentConfig(**config)
        )

    async def _with_fallback(self, op_name: str, op: Callable[[str], Awaitable[T]]) -> T:
        plan = self._model_plan()
        i = 0
        last_exc: BaseException | None = None
        while i < len(plan):
            model, delay = plan[i]
            if delay:
                await asyncio.sleep(delay)
            try:
                result = await asyncio.wait_for(op(model), timeout=self.settings.GEMINI_TIMEOUT_S)
                self._note_success(model)
                return result
            except AppError:
                raise
            except Exception as exc:
                last_exc = exc
                kind = _classify(exc)
                self._note_failure(model, exc)
                metrics.inc("gemini_requests_total", op=op_name, model=model, outcome="error")
                logger.warning(
                    "gemini attempt failed",
                    extra={"op": op_name, "model": model, "error": _describe(exc), "kind": kind},
                )
                if kind == "fatal":
                    break
                if kind == "fallback" and model == plan[0][0]:
                    # Model not found: skip the same-model retry, go straight to the fallback.
                    i = next((j for j, (m, _) in enumerate(plan) if m != model), len(plan))
                    continue
                i += 1
        logger.error("gemini unavailable", extra={"op": op_name, "error": _describe(last_exc) if last_exc else None})
        raise _give_up(op_name, last_exc)

    async def _structured(self, op_name: str, schema: type[M], system: str, contents: list[Any]) -> M:
        self._sdk()  # fail fast (not_configured) before any attempt

        async def op(model: str) -> M:
            attempt_contents = list(contents)
            for attempt in range(2):
                started = time.perf_counter()
                resp = await self._generate(
                    model,
                    attempt_contents,
                    {
                        "system_instruction": system,
                        "temperature": STRUCTURED_TEMPERATURE,
                        "response_mime_type": "application/json",
                        "response_schema": schema,
                    },
                )
                _log_usage(resp, op=op_name, model=model, started=started)
                try:
                    parsed = getattr(resp, "parsed", None)
                    if isinstance(parsed, schema):
                        return parsed
                    text = _strip_fences(_response_text(resp) or (resp.text or ""))
                    if not text:
                        raise _BadResponse("empty response")
                    return schema.model_validate_json(text)
                except (ValidationError, ValueError, _BadResponse, json.JSONDecodeError) as exc:
                    logger.warning(
                        "gemini structured output invalid",
                        extra={"op": op_name, "model": model, "attempt": attempt + 1, "error": type(exc).__name__},
                    )
                    attempt_contents = [*contents, prompts.JSON_REPAIR_SUFFIX]
            raise AppError("AI_BAD_RESPONSE", "The AI returned an invalid response. Please try again.", 502)

        return await self._with_fallback(op_name, op)

    # ------------------------------------------------------------------ structured calls

    async def analyze_food_image(
        self, image: bytes, mime: str, *, hints: list[dict[str, Any]], user_ctx: str, description: str | None
    ) -> FoodAnalysisLLM:
        prompt = prompts.food_image_prompt(user_ctx=user_ctx, hints=hints, description=description)
        contents = [types.Part.from_bytes(data=image, mime_type=mime), prompt]
        return await self._structured("analyze_food_image", FoodAnalysisLLM, prompts.SYSTEM_FOOD_ANALYST, contents)

    async def estimate_from_text(self, text: str, *, user_ctx: str) -> FoodAnalysisLLM:
        prompt = prompts.text_estimate_prompt(text=text, user_ctx=user_ctx)
        return await self._structured("estimate_from_text", FoodAnalysisLLM, prompts.SYSTEM_FOOD_ANALYST, [prompt])

    async def generate_tips(
        self, *, items: list[dict[str, Any]], totals: dict[str, Any], flags: list[dict[str, Any]], user_ctx: str
    ) -> TipsLLM:
        prompt = prompts.tips_prompt(items=items, totals=totals, flags=flags, user_ctx=user_ctx)
        return await self._structured("generate_tips", TipsLLM, prompts.SYSTEM_COACH, [prompt])

    async def daily_insight(self, *, day_summary: dict[str, Any], user_ctx: str) -> InsightLLM:
        prompt = prompts.daily_insight_prompt(day_summary=day_summary, user_ctx=user_ctx)
        return await self._structured("daily_insight", InsightLLM, prompts.SYSTEM_COACH, [prompt])

    async def suggest_recipes(
        self, *, ingredients: list[str], kitchen: str, count: int, user_ctx: str, note: str | None
    ) -> RecipesLLM:
        prompt = prompts.recipe_prompt(
            ingredients=ingredients, kitchen=kitchen, count=count, user_ctx=user_ctx, note=note
        )
        return await self._structured("suggest_recipes", RecipesLLM, prompts.SYSTEM_COACH, [prompt])

    # ------------------------------------------------------------------ chat

    @staticmethod
    def _contents(history: list[ChatHistoryItem]) -> list[types.Content]:
        contents: list[types.Content] = []
        for h in history:
            if h.role == "user":
                parts: list[types.Part] = []
                if h.image:
                    parts.append(types.Part.from_bytes(data=h.image, mime_type=h.image_mime or "image/jpeg"))
                if h.text:
                    parts.append(types.Part.from_text(text=h.text))
                if parts:
                    contents.append(types.Content(role="user", parts=parts))
            elif h.role == "model":
                if isinstance(h.raw, types.Content):
                    contents.append(h.raw)  # replays thought signatures for function calling
                    continue
                parts = [types.Part.from_text(text=h.text)] if h.text else []
                parts += [
                    types.Part(function_call=types.FunctionCall(id=fc.id, name=fc.name, args=fc.args))
                    for fc in h.function_calls
                ]
                if parts:
                    contents.append(types.Content(role="model", parts=parts))
            else:  # tool results
                contents.append(
                    types.Content(
                        role="user",
                        parts=[
                            types.Part(
                                function_response=types.FunctionResponse(id=r.id, name=r.name, response=r.response)
                            )
                            for r in h.function_results
                        ],
                    )
                )
        return contents

    @staticmethod
    def _chat_config(system: str, tools: list[ToolSpec] | None) -> types.GenerateContentConfig:
        return types.GenerateContentConfig(**GeminiClient._chat_kwargs(system, tools))

    @staticmethod
    def _chat_kwargs(system: str, tools: list[ToolSpec] | None) -> dict[str, Any]:
        kwargs: dict[str, Any] = {"system_instruction": system, "temperature": CHAT_TEMPERATURE}
        if tools:
            kwargs["tools"] = [
                types.Tool(
                    function_declarations=[
                        types.FunctionDeclaration(
                            name=t.name, description=t.description, parameters_json_schema=t.parameters
                        )
                        for t in tools
                    ]
                )
            ]
            kwargs["automatic_function_calling"] = types.AutomaticFunctionCallingConfig(disable=True)
        return kwargs

    @staticmethod
    def _function_calls(parts: list[Any]) -> list[FunctionCall]:
        calls = []
        for p in parts:
            fc = getattr(p, "function_call", None)
            if fc is not None and fc.name:
                calls.append(FunctionCall(name=fc.name, args=dict(fc.args or {}), id=fc.id))
        return calls

    async def chat_turn(self, *, system: str, history: list[ChatHistoryItem], tools: list[ToolSpec]) -> ChatTurn:
        self._sdk()
        contents = self._contents(history)
        config = self._chat_kwargs(system, tools)

        async def op(model: str) -> ChatTurn:
            started = time.perf_counter()
            resp = await self._generate(model, contents, config)
            _log_usage(resp, op="chat_turn", model=model, started=started)
            try:
                content = resp.candidates[0].content
                parts = list(content.parts or [])
            except (AttributeError, IndexError, TypeError):
                content, parts = None, []
            return ChatTurn(text=_response_text(resp) or None, function_calls=self._function_calls(parts), raw=content)

        return await self._with_fallback("chat_turn", op)

    async def chat_stream(
        self, *, system: str, history: list[ChatHistoryItem], tools: list[ToolSpec] | None = None
    ) -> AsyncIterator[StreamChunk]:
        """Stream the answer. Retries/fallback apply only until the first chunk has been yielded."""
        client = self._sdk()
        contents = self._contents(history)
        base_config = self._chat_kwargs(system, tools)
        timeout = self.settings.GEMINI_TIMEOUT_S
        plan = self._model_plan()
        i = 0
        last_exc: BaseException | None = None
        while i < len(plan):
            model, delay = plan[i]
            if delay:
                await asyncio.sleep(delay)
            yielded = False
            started = time.perf_counter()
            all_parts: list[Any] = []
            text_buf: list[str] = []
            thinking = self._thinking(model)
            config = types.GenerateContentConfig(
                **base_config, **({"thinking_config": thinking} if thinking is not None else {})
            )
            try:
                stream = await asyncio.wait_for(
                    client.aio.models.generate_content_stream(model=model, contents=contents, config=config),
                    timeout=timeout,
                )
                iterator = stream.__aiter__()
                while True:
                    try:
                        chunk = await asyncio.wait_for(iterator.__anext__(), timeout=timeout)
                    except StopAsyncIteration:
                        break
                    try:
                        parts = list(chunk.candidates[0].content.parts or [])
                    except (AttributeError, IndexError, TypeError):
                        parts = []
                    all_parts.extend(parts)
                    delta = "".join(
                        p.text for p in parts if getattr(p, "text", None) and not getattr(p, "thought", False)
                    )
                    if delta:
                        text_buf.append(delta)
                        yielded = True
                        yield StreamChunk(text=delta)
                self._note_success(model)
                elapsed = time.perf_counter() - started
                logger.info("gemini stream", extra={"model": model, "latency_ms": round(elapsed * 1000)})
                _record_success("chat_stream", model, elapsed, None, None)
                yield StreamChunk(
                    final=ChatTurn(
                        text="".join(text_buf) or None,
                        function_calls=self._function_calls(all_parts),
                        raw=types.Content(role="model", parts=all_parts),
                    )
                )
                return
            except AppError:
                raise
            except Exception as exc:
                if not yielded and thinking is not None and self._rejects_thinking(exc, model):
                    continue  # same model again, without the thinking setting
                last_exc = exc
                kind = _classify(exc)
                self._note_failure(model, exc)
                metrics.inc("gemini_requests_total", op="chat_stream", model=model, outcome="error")
                logger.warning("gemini stream failed", extra={"model": model, "error": _describe(exc), "kind": kind})
                if yielded or kind == "fatal":
                    raise _give_up("chat_stream", exc) from exc
                if kind == "fallback" and model == plan[0][0]:
                    i = next((j for j, (m, _) in enumerate(plan) if m != model), len(plan))
                    continue
                i += 1
        raise _give_up("chat_stream", last_exc)


# ---------------------------------------------------------------------- diagnostics (smoke script)


async def ping(api_key: str, *, model: str, use_vertex: bool, timeout_s: float = 30) -> str:
    """Send 'Reply with OK' to a model. Raises the SDK error on failure (used by scripts/smoke_gemini.py)."""
    client = make_sdk_client(api_key, use_vertex, timeout_s)
    resp = await client.aio.models.generate_content(model=model, contents="Reply with OK")
    return (_response_text(resp) or resp.text or "").strip()


async def list_model_names(api_key: str, *, use_vertex: bool) -> list[str]:
    """Names of models that support generateContent (best effort)."""
    client = make_sdk_client(api_key, use_vertex, 30)
    names: list[str] = []
    pager = await client.aio.models.list()
    async for m in pager:
        actions = getattr(m, "supported_actions", None) or []
        if not actions or "generateContent" in actions:
            names.append((m.name or "").split("/")[-1])
    return names
