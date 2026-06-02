"""Anthropic model provider — Claude API."""

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

DEFAULT_BASE_URL = "https://api.anthropic.com"


class AnthropicProvider(ModelProvider):
    """Provider for Anthropic Claude models."""

    def __init__(
        self,
        api_key: str,
        default_model: str = "claude-haiku-4-5-20251001",
        base_url: str = DEFAULT_BASE_URL,
    ) -> None:
        self._api_key = api_key
        self._default_model = default_model
        self._client = httpx.AsyncClient(
            base_url=base_url,
            timeout=30.0,
            headers={
                "x-api-key": self._api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
        )

    @property
    def family(self) -> ModelFamily:
        return ModelFamily.ANTHROPIC

    @property
    def available_models(self) -> list[str]:
        return [
            "claude-haiku-4-5-20251001",
            "claude-sonnet-4-6",
        ]

    async def complete(self, request: CompletionRequest) -> CompletionResponse:
        model_id = request.model_id or self._default_model
        start = time.monotonic()

        try:
            response = await self._client.post(
                "/v1/messages",
                json={
                    "model": model_id,
                    "max_tokens": request.max_tokens,
                    "temperature": request.temperature,
                    "system": request.system_prompt,
                    "messages": [
                        {"role": "user", "content": request.user_prompt},
                    ],
                },
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as e:
            retryable = e.response.status_code in (429, 500, 502, 503, 529)
            raise ProviderError(
                f"Anthropic API error: {e.response.status_code}", retryable=retryable
            ) from e
        except httpx.TimeoutException as e:
            raise ProviderError("Anthropic API timed out", retryable=True) from e
        except httpx.TransportError as e:
            raise ProviderError("Anthropic API not reachable", retryable=True) from e

        latency_ms = int((time.monotonic() - start) * 1000)
        try:
            data = response.json()
        except ValueError as e:
            raise ProviderError(
                f"Anthropic returned a non-JSON body (HTTP {response.status_code})",
                retryable=True,
            ) from e

        content = ""
        for block in data.get("content", []):
            if block.get("type") == "text":
                content += block.get("text", "")

        usage = data.get("usage", {})

        return CompletionResponse(
            content=content,
            model_id=model_id,
            latency_ms=latency_ms,
            input_tokens=usage.get("input_tokens"),
            output_tokens=usage.get("output_tokens"),
        )

    async def health_check(self) -> bool:
        try:
            # GET /v1/models is a non-generating (non-billable) probe; the old
            # POST /v1/messages probe issued a real inference call. 200 = healthy;
            # 401/403 = reachable but unauthorized (mirrors the other providers).
            response = await self._client.get("/v1/models")
            return response.status_code in (200, 401, 403)
        except httpx.HTTPError:
            return False

    async def close(self) -> None:
        await self._client.aclose()
