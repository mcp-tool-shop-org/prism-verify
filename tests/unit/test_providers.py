"""Provider request-shape tests — the v0.3.0 health-pass fixes.

Covers credential handling (Google key in header, not URL) and the per-model request
param shapes (OpenAI max_completion_tokens / reasoning temperature; Ollama format=json +
think=false), all against respx mocks so no network is touched.
"""

from __future__ import annotations

import json

import httpx
import respx

from prism.providers.base import CompletionRequest
from prism.providers.google import GoogleProvider
from prism.providers.ollama import OllamaProvider
from prism.providers.openai import OpenAIProvider


def _req(model_id: str) -> CompletionRequest:
    return CompletionRequest(system_prompt="s", user_prompt="u", model_id=model_id)


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
