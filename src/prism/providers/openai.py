"""OpenAI model provider — GPT API."""

from __future__ import annotations

import time

import httpx

from prism.core.types import ModelFamily
from prism.providers.base import (
    CompletionRequest,
    CompletionResponse,
    ModelProvider,
    ProviderError,
)

DEFAULT_BASE_URL = "https://api.openai.com"


def _is_reasoning_model(model_id: str) -> bool:
    """OpenAI reasoning models (o-series, GPT-5) reject the deprecated ``max_tokens`` and a
    non-default ``temperature``; they require ``max_completion_tokens`` and the default
    temperature. (OpenAI API reference: ``max_tokens`` is deprecated and GPT-5 returns
    "Unsupported parameter: 'max_tokens' is not supported with this model.")
    """
    m = model_id.lower()
    return m.startswith(("o1", "o3", "o4", "gpt-5"))


class OpenAIProvider(ModelProvider):
    """Provider for OpenAI models."""

    def __init__(
        self,
        api_key: str,
        default_model: str = "gpt-5.4-mini",
        base_url: str = DEFAULT_BASE_URL,
    ) -> None:
        self._api_key = api_key
        self._default_model = default_model
        self._client = httpx.AsyncClient(
            base_url=base_url,
            timeout=30.0,
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
        )

    @property
    def family(self) -> ModelFamily:
        return ModelFamily.OPENAI

    @property
    def available_models(self) -> list[str]:
        return [
            "gpt-5.4-mini",
            "gpt-5",
            "gpt-5.5",
        ]

    def _build_body(self, model_id: str, request: CompletionRequest) -> dict[str, object]:
        """Build the chat-completions body with the correct param shape per model.

        ``max_completion_tokens`` replaces the deprecated ``max_tokens`` (GPT-5/o-series
        reject ``max_tokens`` outright). Reasoning models also reject a non-default
        ``temperature``, so it is sent only for non-reasoning chat models.
        """
        body: dict[str, object] = {
            "model": model_id,
            "max_completion_tokens": request.max_tokens,
            "messages": [
                {"role": "system", "content": request.system_prompt},
                {"role": "user", "content": request.user_prompt},
            ],
        }
        if not _is_reasoning_model(model_id):
            body["temperature"] = request.temperature
        return body

    async def complete(self, request: CompletionRequest) -> CompletionResponse:
        model_id = request.model_id or self._default_model
        start = time.monotonic()

        try:
            response = await self._client.post(
                "/v1/chat/completions",
                json=self._build_body(model_id, request),
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as e:
            retryable = e.response.status_code in (429, 500, 502, 503)
            raise ProviderError(
                f"OpenAI API error: {e.response.status_code}", retryable=retryable
            ) from e
        except httpx.ConnectError as e:
            raise ProviderError("OpenAI API not reachable", retryable=True) from e

        latency_ms = int((time.monotonic() - start) * 1000)
        data = response.json()

        if isinstance(data, dict) and data.get("error"):
            raise ProviderError(f"OpenAI API error: {data['error']}", retryable=False)
        choices = data.get("choices") if isinstance(data, dict) else None
        first = choices[0] if isinstance(choices, list) and choices else None
        message = first.get("message") if isinstance(first, dict) else None
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, str):
            raise ProviderError(
                "OpenAI returned a malformed response (missing choices[0].message.content)",
                retryable=False,
            )
        usage = data.get("usage", {}) if isinstance(data, dict) else {}

        return CompletionResponse(
            content=content,
            model_id=model_id,
            latency_ms=latency_ms,
            input_tokens=usage.get("prompt_tokens"),
            output_tokens=usage.get("completion_tokens"),
        )

    async def health_check(self) -> bool:
        try:
            response = await self._client.get("/v1/models")
            return response.status_code == 200
        except httpx.HTTPError:
            return False

    async def close(self) -> None:
        await self._client.aclose()
