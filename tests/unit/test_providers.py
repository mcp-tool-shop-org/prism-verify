"""Provider request-shape tests — the v0.3.0 health-pass fixes.

Covers credential handling (Google key in header, not URL) and the per-model request
param shapes (OpenAI max_completion_tokens / reasoning temperature; Ollama format=json +
think=false), all against respx mocks so no network is touched.
"""

from __future__ import annotations

import json

import httpx
import pytest
import respx

from prism.providers.anthropic import AnthropicProvider
from prism.providers.base import CompletionRequest, ProviderError
from prism.providers.google import GoogleProvider
from prism.providers.ollama import OllamaProvider
from prism.providers.openai import OpenAIProvider


def _req(model_id: str) -> CompletionRequest:
    return CompletionRequest(system_prompt="s", user_prompt="u", model_id=model_id)


# (provider_factory, completion_endpoint_url, model_id) per provider — the endpoint each
# provider's complete() POSTs to, for driving a ReadTimeout / non-JSON body against it.
_GEMINI_URL = "http://g/v1beta/models/gemini-2.5-pro:generateContent"
_PROVIDER_CASES = [
    (
        lambda: AnthropicProvider(api_key="k", base_url="http://a"),
        "http://a/v1/messages",
        "claude-haiku-4-5-20251001",
    ),
    (lambda: GoogleProvider(api_key="k", base_url="http://g"), _GEMINI_URL, "gemini-2.5-pro"),
    (
        lambda: OpenAIProvider(api_key="k", base_url="http://o"),
        "http://o/v1/chat/completions",
        "gpt-5.4-mini",
    ),
    (lambda: OllamaProvider(base_url="http://ol"), "http://ol/api/chat", "mistral-small:24b"),
]


@pytest.mark.parametrize("factory,url,model_id", _PROVIDER_CASES)
async def test_read_timeout_maps_to_retryable_provider_error(factory, url, model_id):
    """PROV-A-004 / PROV-A-001/002: a ReadTimeout on the completion endpoint surfaces as a
    ProviderError(retryable=True), never a raw httpx.ReadTimeout escaping complete()."""
    provider = factory()
    with respx.mock:
        respx.post(url).mock(side_effect=httpx.ReadTimeout("read timed out"))
        with pytest.raises(ProviderError) as exc:
            await provider.complete(_req(model_id))
    assert exc.value.retryable is True
    await provider.close()


@pytest.mark.parametrize("factory,url,model_id", _PROVIDER_CASES)
async def test_non_json_200_body_maps_to_provider_error(factory, url, model_id):
    """PROV-A-001/002: a 200 with an HTML/non-JSON body (a captive portal / proxy error page)
    surfaces as a structured ProviderError, not a raw json.JSONDecodeError escaping complete()."""
    provider = factory()
    with respx.mock:
        respx.post(url).mock(
            return_value=httpx.Response(
                200, text="<html>nope</html>", headers={"content-type": "text/html"}
            )
        )
        with pytest.raises(ProviderError):
            await provider.complete(_req(model_id))
    await provider.close()


async def test_google_sends_key_in_header_not_url():
    provider = GoogleProvider(api_key="secret-key", base_url="http://g")
    captured: dict[str, str | None] = {}

    def _capture(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["header"] = request.headers.get("x-goog-api-key")
        return httpx.Response(
            200, json={"candidates": [{"content": {"parts": [{"text": "{}"}]}}]}
        )

    with respx.mock:
        respx.post("http://g/v1beta/models/gemini-2.5-pro:generateContent").mock(
            side_effect=_capture
        )
        await provider.complete(_req("gemini-2.5-pro"))

    assert captured["header"] == "secret-key"
    assert "key=" not in (captured["url"] or "")
    assert "secret-key" not in (captured["url"] or "")
    await provider.close()


async def test_openai_uses_max_completion_tokens_and_omits_temperature_for_reasoning():
    provider = OpenAIProvider(api_key="k", base_url="http://o")
    captured: dict[str, object] = {}

    def _capture(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"choices": [{"message": {"content": "{}"}}]})

    with respx.mock:
        respx.post("http://o/v1/chat/completions").mock(side_effect=_capture)
        await provider.complete(_req("gpt-5.4-mini"))

    body = captured["body"]
    assert "max_completion_tokens" in body
    assert "max_tokens" not in body
    assert "temperature" not in body
    await provider.close()


async def test_openai_includes_temperature_for_non_reasoning_model():
    provider = OpenAIProvider(api_key="k", base_url="http://o")
    captured: dict[str, object] = {}

    def _capture(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"choices": [{"message": {"content": "{}"}}]})

    with respx.mock:
        respx.post("http://o/v1/chat/completions").mock(side_effect=_capture)
        await provider.complete(_req("gpt-4.1-mini"))

    body = captured["body"]
    assert "temperature" in body
    assert "max_completion_tokens" in body
    await provider.close()


async def test_ollama_sends_format_json_and_disables_thinking():
    provider = OllamaProvider(base_url="http://ol")
    captured: dict[str, object] = {}

    def _capture(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"message": {"content": "{}"}})

    with respx.mock:
        respx.post("http://ol/api/chat").mock(side_effect=_capture)
        await provider.complete(_req("mistral-small:24b"))

    body = captured["body"]
    assert body["format"] == "json"
    assert body["think"] is False
    await provider.close()


def test_ollama_default_model_is_non_thinking():
    # qwen3:32b is a thinking model that starves the JSON budget; the pin is mistral-small.
    assert OllamaProvider().available_models == ["mistral-small:24b"]


# PRV-B-001: provider observability — a failed call must emit a structured WARNING carrying
# provider + model + status (and NEVER the API key), so a partial outage is visible before it
# surfaces downstream as VERIFIER_UNAVAILABLE.
_OBS_CASES = [
    (
        lambda: AnthropicProvider(api_key="super-secret-key", base_url="http://a"),
        "http://a/v1/messages",
        "claude-haiku-4-5-20251001",
        "anthropic",
    ),
    (
        lambda: GoogleProvider(api_key="super-secret-key", base_url="http://g"),
        _GEMINI_URL,
        "gemini-2.5-pro",
        "google",
    ),
    (
        lambda: OpenAIProvider(api_key="super-secret-key", base_url="http://o"),
        "http://o/v1/chat/completions",
        "gpt-5.4-mini",
        "openai",
    ),
    (
        lambda: OllamaProvider(base_url="http://ol"),
        "http://ol/api/chat",
        "mistral-small:24b",
        "ollama",
    ),
]


@pytest.mark.parametrize("factory,url,model_id,provider_name", _OBS_CASES)
async def test_failed_call_logs_warning_with_provider_model_status(
    factory, url, model_id, provider_name, caplog
):
    provider = factory()
    with respx.mock:
        respx.post(url).mock(return_value=httpx.Response(503, json={"error": "down"}))
        with caplog.at_level("WARNING", logger="prism.providers"):
            with pytest.raises(ProviderError):
                await provider.complete(_req(model_id))
    await provider.close()

    warnings = [r for r in caplog.records if r.levelname == "WARNING"]
    assert warnings, "a failed provider call must emit a WARNING"
    rec = warnings[-1]
    assert rec.provider == provider_name
    assert rec.model_id == model_id
    assert rec.http_status == 503
    assert hasattr(rec, "latency_ms")
    assert hasattr(rec, "exc_type")
    assert hasattr(rec, "request_id")
    # the key (and only the key) must never reach the logs in any field
    rendered = rec.getMessage() + repr(rec.__dict__)
    assert "super-secret-key" not in rendered


async def test_no_warning_logged_on_success(caplog):
    provider = OpenAIProvider(api_key="super-secret-key", base_url="http://o")
    with respx.mock:
        respx.post("http://o/v1/chat/completions").mock(
            return_value=httpx.Response(200, json={"choices": [{"message": {"content": "{}"}}]})
        )
        with caplog.at_level("WARNING", logger="prism.providers"):
            await provider.complete(_req("gpt-5.4-mini"))
    await provider.close()
    assert not [r for r in caplog.records if r.levelname == "WARNING"]
