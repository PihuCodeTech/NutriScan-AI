"""GeminiClient reliability (SDK calls monkeypatched — no network) and MockGeminiClient behaviour."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest
from google.genai import errors as genai_errors

from app.core.config import Settings
from app.core.errors import AppError
from app.services.llm import gemini_client
from app.services.llm.gemini_client import GeminiClient
from app.services.llm.mock_client import MockGeminiClient, rajma_chawal_fixture
from app.services.llm.schemas import (
    ChatHistoryItem,
    FoodAnalysisLLM,
    FunctionCall,
    FunctionResult,
    TipsLLM,
    ToolSpec,
)


def _settings(**overrides: Any) -> Settings:
    base = {
        "GEMINI_API_KEY": "fake-key",
        "GEMINI_MODEL": "primary-model",
        "GEMINI_FALLBACK_MODEL": "fallback-model",
        "GEMINI_TIMEOUT_S": 2,
        "MOCK_AI": False,
    }
    return Settings(**{**base, **overrides})


def _resp(*, parsed: Any = None, text: str | None = None, parts: list[Any] | None = None) -> SimpleNamespace:
    if parts is None:
        parts = [SimpleNamespace(text=text, thought=False, function_call=None)] if text is not None else []
    content = SimpleNamespace(role="model", parts=parts)
    return SimpleNamespace(
        parsed=parsed,
        text=text,
        candidates=[SimpleNamespace(content=content)],
        usage_metadata=SimpleNamespace(prompt_token_count=10, candidates_token_count=5, total_token_count=15),
    )


class FakeModels:
    def __init__(self, behaviour: dict[str, list[Any]]) -> None:
        self.behaviour = behaviour
        self.calls: list[str] = []

    async def generate_content(self, *, model: str, contents: Any, config: Any) -> Any:
        self.calls.append(model)
        outcome = self.behaviour[model].pop(0) if len(self.behaviour[model]) > 1 else self.behaviour[model][0]
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


def _client(behaviour: dict[str, list[Any]], **settings: Any) -> tuple[GeminiClient, FakeModels]:
    client = GeminiClient(_settings(**settings))
    models = FakeModels(behaviour)
    client._client = SimpleNamespace(aio=SimpleNamespace(models=models))  # type: ignore[assignment]
    return client, models


@pytest.fixture(autouse=True)
def _no_retry_delay(monkeypatch):
    monkeypatch.setattr(gemini_client, "RETRY_DELAY_S", 0)


def _server_error() -> genai_errors.ServerError:
    return genai_errors.ServerError(503, {"error": {"code": 503, "message": "overloaded", "status": "UNAVAILABLE"}})


def _internal_error() -> genai_errors.ServerError:
    return genai_errors.ServerError(500, {"error": {"code": 500, "message": "oops", "status": "INTERNAL"}})


def _client_error(code: int) -> genai_errors.ClientError:
    return genai_errors.ClientError(code, {"error": {"code": code, "message": "nope", "status": "X"}})


async def test_falls_back_when_primary_fails():
    fixture = rajma_chawal_fixture()
    client, models = _client({"primary-model": [_internal_error()], "fallback-model": [_resp(parsed=fixture)]})
    result = await client.estimate_from_text("2 roti and dal", user_ctx="Country: IN")
    assert result == fixture
    assert models.calls == ["primary-model", "primary-model", "fallback-model"]
    assert client.last_model_used == "fallback-model"


async def test_overloaded_503_goes_straight_to_fallback():
    fixture = rajma_chawal_fixture()
    client, models = _client({"primary-model": [_server_error()], "fallback-model": [_resp(parsed=fixture)]})
    assert await client.estimate_from_text("rice", user_ctx="") == fixture
    assert models.calls == ["primary-model", "fallback-model"]


async def test_overloaded_primary_is_skipped_during_cooldown():
    fixture = rajma_chawal_fixture()
    client, models = _client({"primary-model": [_server_error()], "fallback-model": [_resp(parsed=fixture)]})
    await client.estimate_from_text("rice", user_ctx="")
    models.calls.clear()
    await client.estimate_from_text("dal", user_ctx="")
    assert models.calls == ["fallback-model"]  # the struggling primary isn't tried first again


async def test_primary_is_tried_first_again_after_cooldown():
    fixture = rajma_chawal_fixture()
    client, models = _client(
        {"primary-model": [_server_error(), _resp(parsed=fixture)], "fallback-model": [_resp(parsed=fixture)]}
    )
    await client.estimate_from_text("rice", user_ctx="")
    client._cooldown_until["primary-model"] = 0.0  # cooldown elapsed
    models.calls.clear()
    await client.estimate_from_text("dal", user_ctx="")
    assert models.calls == ["primary-model"]
    assert client.last_model_used == "primary-model"


async def test_cooling_primary_is_last_resort_when_fallback_fails():
    fixture = rajma_chawal_fixture()
    client, models = _client(
        {"primary-model": [_server_error(), _resp(parsed=fixture)], "fallback-model": [_resp(parsed=fixture)]}
    )
    await client.estimate_from_text("rice", user_ctx="")
    models.behaviour["fallback-model"] = [_server_error()]
    models.calls.clear()
    assert await client.estimate_from_text("dal", user_ctx="") == fixture
    assert models.calls == ["fallback-model", "primary-model"]


async def test_cooldown_can_be_switched_off():
    fixture = rajma_chawal_fixture()
    client, models = _client(
        {"primary-model": [_server_error()], "fallback-model": [_resp(parsed=fixture)]}, GEMINI_COOLDOWN_S=0
    )
    await client.estimate_from_text("rice", user_ctx="")
    models.calls.clear()
    await client.estimate_from_text("dal", user_ctx="")
    assert models.calls == ["primary-model", "fallback-model"]


async def test_bad_request_does_not_trigger_cooldown():
    fixture = rajma_chawal_fixture()
    client, _ = _client({"primary-model": [_client_error(400)], "fallback-model": [_resp(parsed=fixture)]})
    await client.estimate_from_text("rice", user_ctx="")
    assert not client._cooling("primary-model")


async def test_retry_on_429_then_primary_succeeds():
    fixture = rajma_chawal_fixture()
    client, models = _client({"primary-model": [_client_error(429), _resp(parsed=fixture)], "fallback-model": []})
    await client.estimate_from_text("rice", user_ctx="")
    assert models.calls == ["primary-model", "primary-model"]
    assert client.last_model_used == "primary-model"


async def test_daily_quota_429_goes_straight_to_fallback():
    fixture = rajma_chawal_fixture()
    daily = genai_errors.ClientError(
        429,
        {"error": {"code": 429, "message": "quota", "status": "RESOURCE_EXHAUSTED",
                   "details": [{"violations": [{"quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier"}]}]}},
    )
    client, models = _client({"primary-model": [daily], "fallback-model": [_resp(parsed=fixture)]})
    await client.estimate_from_text("rice", user_ctx="")
    assert models.calls == ["primary-model", "fallback-model"]


async def test_timeout_then_fallback(monkeypatch):
    async def slow(**_: Any) -> Any:
        await asyncio.sleep(5)

    fixture = rajma_chawal_fixture()
    client, models = _client({"primary-model": [], "fallback-model": [_resp(parsed=fixture)]}, GEMINI_TIMEOUT_S=0.05)
    original = models.generate_content

    async def patched(*, model: str, contents: Any, config: Any) -> Any:
        if model == "primary-model":
            models.calls.append(model)
            return await slow()
        return await original(model=model, contents=contents, config=config)

    models.generate_content = patched  # type: ignore[method-assign]
    result = await client.estimate_from_text("rice", user_ctx="")
    assert result == fixture
    assert models.calls == ["primary-model", "fallback-model"]  # a slow model is not retried


async def test_model_not_found_goes_straight_to_fallback():
    fixture = rajma_chawal_fixture()
    client, models = _client({"primary-model": [_client_error(404)], "fallback-model": [_resp(parsed=fixture)]})
    await client.estimate_from_text("rice", user_ctx="")
    assert models.calls == ["primary-model", "fallback-model"]


async def test_all_attempts_fail_raises_ai_unavailable():
    client, models = _client({"primary-model": [_internal_error()], "fallback-model": [_internal_error()]})
    with pytest.raises(AppError) as exc:
        await client.estimate_from_text("rice", user_ctx="")
    assert exc.value.code == "AI_UNAVAILABLE" and exc.value.http_status == 503
    assert len(models.calls) == 3


async def test_auth_error_is_fatal_no_fallback():
    client, models = _client({"primary-model": [_client_error(403)], "fallback-model": [_resp(text="{}")]})
    with pytest.raises(AppError) as exc:
        await client.estimate_from_text("rice", user_ctx="")
    assert exc.value.code == "AI_UNAVAILABLE"
    assert models.calls == ["primary-model"]


async def test_invalid_json_is_reasked_once_then_succeeds():
    good = TipsLLM(tips=["Eat dal"]).model_dump_json()
    client, models = _client({"primary-model": [_resp(text="not json"), _resp(text=f"```json\n{good}\n```")]})
    result = await client.generate_tips(items=[], totals={}, flags=[], user_ctx="")
    assert result.tips == ["Eat dal"]
    assert models.calls == ["primary-model", "primary-model"]


async def test_invalid_json_twice_raises_bad_response():
    client, models = _client({"primary-model": [_resp(text='{"wrong": 1}')]})
    with pytest.raises(AppError) as exc:
        await client.generate_tips(items=[], totals={}, flags=[], user_ctx="")
    assert exc.value.code == "AI_BAD_RESPONSE" and exc.value.http_status == 502
    assert models.calls == ["primary-model", "primary-model"]  # no fallback for bad JSON


async def test_missing_key_raises_ai_unavailable():
    client = GeminiClient(_settings(GEMINI_API_KEY=""))
    with pytest.raises(AppError) as exc:
        await client.estimate_from_text("rice", user_ctx="")
    assert exc.value.code == "AI_UNAVAILABLE"


async def test_chat_turn_parses_function_calls():
    fc_part = SimpleNamespace(
        text=None,
        thought=False,
        function_call=SimpleNamespace(name="get_daily_intake", args={"date": "2026-09-28"}, id="c1"),
    )
    thought = SimpleNamespace(text="thinking...", thought=True, function_call=None)
    client, _ = _client({"primary-model": [_resp(parts=[thought, fc_part])]})
    turn = await client.chat_turn(
        system="sys",
        history=[ChatHistoryItem(role="user", text="how did I do today?")],
        tools=[ToolSpec(name="get_daily_intake", description="d", parameters={"type": "object", "properties": {}})],
    )
    assert turn.text is None
    assert turn.function_calls == [FunctionCall(name="get_daily_intake", args={"date": "2026-09-28"}, id="c1")]


def test_history_to_contents():
    history = [
        ChatHistoryItem(role="user", text="hi", image=b"\xff\xd8jpeg", image_mime="image/jpeg"),
        ChatHistoryItem(role="model", text=None, function_calls=[FunctionCall(name="log_meal", args={"x": 1}, id="a")]),
        ChatHistoryItem(
            role="tool", function_results=[FunctionResult(name="log_meal", response={"result": 1}, id="a")]
        ),
        ChatHistoryItem(role="model", text="done"),
    ]
    contents = GeminiClient._contents(history)
    assert [c.role for c in contents] == ["user", "model", "user", "model"]
    assert contents[0].parts[0].inline_data.mime_type == "image/jpeg"
    assert contents[1].parts[0].function_call.name == "log_meal"
    assert contents[2].parts[0].function_response.response == {"result": 1}


# ---------------------------------------------------------------------- mock client


async def test_mock_image_fixture_and_not_food():
    mock = MockGeminiClient()
    result = await mock.analyze_food_image(b"", "image/jpeg", hints=[], user_ctx="", description=None)
    assert result.meal_name == "Rajma Chawal Plate"
    assert [i.quantity_g for i in result.items] == [150, 150, 50]
    assert len(result.tips) == 2
    rejected = await mock.analyze_food_image(b"", "image/jpeg", hints=[], user_ctx="", description="this is not food")
    assert rejected.is_food is False and rejected.items == []
    assert mock.calls["analyze_food_image"] == 2


async def test_mock_queue_overrides_and_raises():
    mock = MockGeminiClient()
    custom = FoodAnalysisLLM(is_food=True, meal_name="Custom", items=[])
    mock.queue("analyze_food_image", custom)
    mock.queue("analyze_food_image", AppError("AI_UNAVAILABLE", "down", 503))
    assert (await mock.analyze_food_image(b"", "image/jpeg", hints=[], user_ctx="", description=None)) is custom
    with pytest.raises(AppError):
        await mock.analyze_food_image(b"", "image/jpeg", hints=[], user_ctx="", description=None)
    # queue drained → back to the default fixture
    default = await mock.analyze_food_image(b"", "image/jpeg", hints=[], user_ctx="", description=None)
    assert default.meal_name == "Rajma Chawal Plate"


async def test_mock_text_estimate_splits_parts():
    mock = MockGeminiClient()
    result = await mock.estimate_from_text("2 roti, dal and a glass of lassi", user_ctx="")
    names = [i.name for i in result.items]
    assert names == ["Roti", "Dal", "Lassi"]
    assert result.items[0].quantity_g == 80  # 2 × 40 g
    grams = await mock.estimate_from_text("120 g curd", user_ctx="")
    assert grams.items[0].quantity_g == 120
    assert (await mock.estimate_from_text("this is not food", user_ctx="")).is_food is False


async def test_mock_chat_tool_flow():
    mock = MockGeminiClient()
    tools = [ToolSpec(name="x", description="", parameters={})]
    history = [ChatHistoryItem(role="user", text="How did I do today?")]
    turn = await mock.chat_turn(system="", history=history, tools=tools)
    assert turn.function_calls[0].name == "get_daily_intake"
    history += [
        ChatHistoryItem(role="model", function_calls=turn.function_calls),
        ChatHistoryItem(
            role="tool",
            function_results=[
                FunctionResult(
                    name="get_daily_intake",
                    response={"result": {"totals": {"calories": 900}, "targets": {"calories": 2000}}},
                )
            ],
        ),
    ]
    answer = await mock.chat_turn(system="", history=history, tools=tools)
    assert not answer.function_calls and "900 kcal" in answer.text

    log_turn = await mock.chat_turn(
        system="", history=[ChatHistoryItem(role="user", text="log 2 roti and dal for dinner")], tools=tools
    )
    assert log_turn.function_calls[0].args == {"description": "2 roti and dal", "meal_type": "dinner"}


async def test_mock_stream_chunks():
    mock = MockGeminiClient()
    chunks = [c async for c in mock.chat_stream(system="", history=[ChatHistoryItem(role="user", text="hi")])]
    texts = [c.text for c in chunks if c.text]
    assert 3 <= len(texts) <= 6
    assert chunks[-1].final is not None and "".join(texts) == chunks[-1].final.text


# ---------------------------------------------------------------------- streaming


def _chunk(text=None, fc=None):
    parts = []
    if text:
        parts.append(SimpleNamespace(text=text, thought=False, function_call=None))
    if fc:
        parts.append(SimpleNamespace(text=None, thought=False, function_call=fc))
    return SimpleNamespace(candidates=[SimpleNamespace(content=SimpleNamespace(parts=parts))])


class FakeStream:
    def __init__(self, chunks):
        self._chunks = list(chunks)

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self._chunks:
            raise StopAsyncIteration
        item = self._chunks.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item


def _stream_client(plan):
    client = GeminiClient(_settings())
    calls = []

    async def generate_content_stream(*, model, contents, config):
        calls.append(model)
        outcome = plan[model].pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return FakeStream(outcome)

    client._client = SimpleNamespace(
        aio=SimpleNamespace(models=SimpleNamespace(generate_content_stream=generate_content_stream))
    )
    return client, calls


async def test_stream_yields_deltas_and_final_turn():
    client, calls = _stream_client({"primary-model": [[_chunk("Hello "), _chunk("there!")]]})
    chunks = [c async for c in client.chat_stream(system="s", history=[ChatHistoryItem(role="user", text="hi")])]
    assert [c.text for c in chunks if c.text] == ["Hello ", "there!"]
    assert chunks[-1].final.text == "Hello there!" and chunks[-1].final.function_calls == []
    assert calls == ["primary-model"]


async def test_stream_function_call_collected():
    fc = SimpleNamespace(name="get_daily_intake", args={}, id="x")
    client, _ = _stream_client({"primary-model": [[_chunk(fc=fc)]]})
    chunks = [c async for c in client.chat_stream(system="s", history=[ChatHistoryItem(role="user", text="today?")])]
    assert chunks[-1].final.function_calls[0].name == "get_daily_intake"


async def test_stream_falls_back_before_first_chunk():
    client, calls = _stream_client(
        {"primary-model": [_internal_error(), _internal_error()], "fallback-model": [[_chunk("ok")]]}
    )
    chunks = [c async for c in client.chat_stream(system="s", history=[ChatHistoryItem(role="user", text="hi")])]
    assert chunks[-1].final.text == "ok"
    assert calls == ["primary-model", "primary-model", "fallback-model"]
    assert client.last_model_used == "fallback-model"


async def test_stream_skips_overloaded_primary_on_the_next_message():
    client, calls = _stream_client({"primary-model": [_server_error()], "fallback-model": [[_chunk("ok")], [_chunk("ok")]]})
    history = [ChatHistoryItem(role="user", text="hi")]
    [c async for c in client.chat_stream(system="s", history=history)]
    assert calls == ["primary-model", "fallback-model"]  # a 503 "high demand" isn't retried on the same model
    calls.clear()
    [c async for c in client.chat_stream(system="s", history=history)]
    assert calls == ["fallback-model"]


async def test_stream_error_after_first_chunk_is_ai_unavailable():
    client, calls = _stream_client({"primary-model": [[_chunk("partial"), _server_error()]]})
    with pytest.raises(AppError) as exc:
        async for _ in client.chat_stream(system="s", history=[ChatHistoryItem(role="user", text="hi")]):
            pass
    assert exc.value.code == "AI_UNAVAILABLE"
    assert calls == ["primary-model"]  # no retry once text was sent to the user


def test_pick_models_prefers_newest_stable_flash():
    import importlib.util
    from pathlib import Path

    spec = importlib.util.spec_from_file_location("smoke", Path("scripts/smoke_gemini.py"))
    smoke = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(smoke)
    names = [
        "gemini-2.5-flash",
        "gemini-3.8-flash",
        "gemini-3.9-flash-preview",
        "gemini-3.5-flash-lite",
        "gemini-2.5-flash-lite",
        "gemini-3.8-flash-image",
        "gemini-3.8-pro",
    ]
    assert smoke.pick_models(names) == ("gemini-3.8-flash", "gemini-3.5-flash-lite")
