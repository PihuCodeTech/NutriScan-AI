"""AI failures carry a specific reason (`details.reason`) so the app can tell a bad key from a busy model."""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from google.genai import errors as genai_errors

from app.core.errors import AppError
from app.services.llm import gemini_client
from app.services.llm.mock_client import rajma_chawal_fixture
from tests.test_llm_client import _client, _resp


@pytest.fixture(autouse=True)
def _no_retry_delay(monkeypatch):
    monkeypatch.setattr(gemini_client, "RETRY_DELAY_S", 0)


def _err(code: int, message: str = "nope", status: str = "X", details: Any = None) -> genai_errors.ClientError:
    body: dict[str, Any] = {"code": code, "message": message, "status": status}
    if details is not None:
        body["details"] = details
    return genai_errors.ClientError(code, {"error": body})


async def _reason(client) -> AppError:
    with pytest.raises(AppError) as exc:
        await client.estimate_from_text("rice", user_ctx="")
    assert exc.value.code == "AI_UNAVAILABLE" and exc.value.http_status == 503
    return exc.value


async def test_invalid_api_key_400_is_fatal_with_auth_reason():
    bad_key = _err(
        400,
        "API key not valid. Please pass a valid API key.",
        "INVALID_ARGUMENT",
        [{"@type": "type.googleapis.com/google.rpc.ErrorInfo", "reason": "API_KEY_INVALID"}],
    )
    client, models = _client({"primary-model": [bad_key], "fallback-model": [_resp(text="{}")]})
    err = await _reason(client)
    assert err.details == {"reason": "auth"}
    assert "GEMINI_API_KEY" in err.message
    assert models.calls == ["primary-model"]  # no point trying the fallback with the same key


async def test_permission_denied_403_has_auth_reason():
    client, _ = _client({"primary-model": [_err(403, "Permission denied", "PERMISSION_DENIED")]})
    assert (await _reason(client)).details == {"reason": "auth"}


async def test_other_400_falls_back_to_the_fallback_model():
    fixture = rajma_chawal_fixture()
    unsupported = _err(400, "response_schema is not supported by this model", "INVALID_ARGUMENT")
    client, models = _client({"primary-model": [unsupported], "fallback-model": [_resp(parsed=fixture)]})
    assert await client.estimate_from_text("rice", user_ctx="") == fixture
    assert models.calls == ["primary-model", "fallback-model"]


async def test_quota_exhausted_everywhere_has_quota_reason():
    quota = _err(429, "Resource has been exhausted", "RESOURCE_EXHAUSTED")
    client, models = _client({"primary-model": [quota], "fallback-model": [quota]})
    err = await _reason(client)
    assert err.details == {"reason": "quota"}
    assert models.calls == ["primary-model", "primary-model", "fallback-model"]


async def test_models_not_found_has_model_reason():
    client, _ = _client({"primary-model": [_err(404)], "fallback-model": [_err(404)]})
    err = await _reason(client)
    assert err.details == {"reason": "model"}
    assert "smoke_gemini" in err.message


async def test_network_failure_has_network_reason():
    down = httpx.ConnectError("connection refused")
    client, _ = _client({"primary-model": [down], "fallback-model": [down]})
    assert (await _reason(client)).details == {"reason": "network"}


async def test_missing_key_has_not_configured_reason():
    client, _ = _client({"primary-model": []}, GEMINI_API_KEY="")
    err = await _reason(client)
    assert err.details == {"reason": "not_configured"}


async def test_scan_endpoint_returns_reason_to_the_frontend(client, auth_headers, sample_jpeg, mock_llm):
    mock_llm.queue(
        "analyze_food_image",
        AppError("AI_UNAVAILABLE", "The Gemini API rejected the server's API key.", 503, {"reason": "auth"}),
    )
    r = await client.post("/api/v1/scans", headers=auth_headers, files={"image": ("p.jpg", sample_jpeg, "image/jpeg")})
    body = r.json()
    assert r.status_code == 503
    assert body["code"] == "AI_UNAVAILABLE" and body["details"] == {"reason": "auth"}
    assert "API key" in body["message"]


def test_network_error_helper_used_by_smoke_script():
    assert gemini_client.is_network_error(httpx.ConnectError("refused"))
    assert gemini_client.is_network_error(TimeoutError())
    assert not gemini_client.is_network_error(_err(400, "API key not valid", "INVALID_ARGUMENT"))


class _RecordingModels:
    """Records the config of each call; raises the queued outcomes in order."""

    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.configs = []

    async def generate_content(self, *, model, contents, config):
        self.configs.append((model, config))
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


def _recording_client(outcomes, **settings):
    from types import SimpleNamespace

    client, _ = _client({"primary-model": []}, **settings)
    models = _RecordingModels(outcomes)
    client._client = SimpleNamespace(aio=SimpleNamespace(models=models))
    return client, models


async def test_structured_calls_ask_for_low_thinking():
    fixture = rajma_chawal_fixture()
    client, models = _recording_client([_resp(parsed=fixture)])
    await client.estimate_from_text("rice", user_ctx="")
    ((_, config),) = models.configs
    assert str(config.thinking_config.thinking_level).upper().endswith("LOW")


async def test_model_that_rejects_thinking_is_retried_without_it():
    fixture = rajma_chawal_fixture()
    refuse = _err(400, "Thinking level is not supported for this model.", "INVALID_ARGUMENT")
    client, models = _recording_client([refuse, _resp(parsed=fixture), _resp(parsed=fixture)])
    assert await client.estimate_from_text("rice", user_ctx="") == fixture
    assert [c.thinking_config is None for _, c in models.configs] == [False, True]
    await client.estimate_from_text("dal", user_ctx="")  # remembered: no thinking setting next time
    assert models.configs[-1][1].thinking_config is None


async def test_thinking_can_be_switched_off():
    client, models = _recording_client([_resp(parsed=rajma_chawal_fixture())], GEMINI_THINKING_LEVEL="")
    await client.estimate_from_text("rice", user_ctx="")
    assert models.configs[0][1].thinking_config is None


async def test_504_deadline_goes_straight_to_fallback():
    fixture = rajma_chawal_fixture()
    slow = genai_errors.ServerError(
        504, {"error": {"code": 504, "message": "Deadline expired", "status": "DEADLINE_EXCEEDED"}}
    )
    client, models = _client({"primary-model": [slow], "fallback-model": [_resp(parsed=fixture)]})
    assert await client.estimate_from_text("rice", user_ctx="") == fixture
    assert models.calls == ["primary-model", "fallback-model"]
