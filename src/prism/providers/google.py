"""Google Gemini model provider."""

from __future__ import annotations

import time

import httpx

from prism.core.types import ModelFamily
from prism.providers.base import (
    CompletionRequest,
    CompletionResponse,
    ModelProvider,
    ProviderError,
    log_provider_failure,
    log_provider_success,
)

DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com"
_NAME = "google"


class GoogleProvider(ModelProvider):
    """Provider for Google Gemini models (GA SKU only, never preview)."""

    def __init__(
        self,
        api_key: str,
        default_model: str = "gemini-2.5-pro",
        base_url: str = DEFAULT_BASE_URL,
    ) -> None:
        self._api_key = api_key
        self._default_model = default_model
        self._base_url = base_url
        # The API key travels in the x-goog-api-key header, never the URL query string.
        # A `?key=` query leaks the credential into httpx error reprs, tracebacks, proxy
        # logs, and access logs; a header does not.
        self._client = httpx.AsyncClient(
            timeout=30.0,
            headers={
                "x-goog-api-key": self._api_key,
                "Content-Type": "application/json",
            },
        )

    @property
    def family(self) -> ModelFamily:
        return ModelFamily.GOOGLE

    @property
    def available_models(self) -> list[str]:
        return ["gemini-2.5-pro"]

    async def complete(self, request: CompletionRequest) -> CompletionResponse:
        model_id = request.model_id or self._default_model
        start = time.monotonic()

        url = f"{self._base_url}/v1beta/models/{model_id}:generateContent"

        try:
            response = await self._client.post(
                url,
                json={
                    "system_instruction": {
                        "parts": [{"text": request.system_prompt}]
                    },
                    "contents": [
                        {
                            "parts": [{"text": request.user_prompt}],
                            "role": "user",
                        }
                    ],
                    "generationConfig": {
                        "temperature": request.temperature,
                        "maxOutputTokens": request.max_tokens,
                    },
                },
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as e:
            elapsed = int((time.monotonic() - start) * 1000)
            log_provider_failure(
                _NAME, model_id, e, latency_ms=elapsed, status=e.response.status_code
            )
            retryable = e.response.status_code in (429, 500, 502, 503)
            raise ProviderError(
                f"Gemini API error: {e.response.status_code}", retryable=retryable
            ) from e
        except httpx.TimeoutException as e:
            elapsed = int((time.monotonic() - start) * 1000)
            log_provider_failure(_NAME, model_id, e, latency_ms=elapsed)
            raise ProviderError("Gemini API timed out", retryable=True) from e
        except httpx.TransportError as e:
            elapsed = int((time.monotonic() - start) * 1000)
            log_provider_failure(_NAME, model_id, e, latency_ms=elapsed)
            raise ProviderError("Gemini API not reachable", retryable=True) from e

        latency_ms = int((time.monotonic() - start) * 1000)
        try:
            data = response.json()
        except ValueError as e:
            log_provider_failure(
                _NAME, model_id, e, latency_ms=latency_ms, status=response.status_code
            )
            raise ProviderError(
                f"Gemini returned a non-JSON body (HTTP {response.status_code})",
                retryable=True,
            ) from e

        # Extract text from Gemini response. Guard the shape: a non-dict body, a
        # missing/empty `candidates`, or a non-dict first element must not raise
        # IndexError/AttributeError out of complete().
        candidates = data.get("candidates") if isinstance(data, dict) else None
        first = candidates[0] if isinstance(candidates, list) and candidates else None
        content = ""
        if isinstance(first, dict):
            inner = first.get("content")
            parts = inner.get("parts", []) if isinstance(inner, dict) else []
            if isinstance(parts, list):
                content = "".join(
                    p.get("text", "") for p in parts if isinstance(p, dict)
                )

        usage = data.get("usageMetadata", {}) if isinstance(data, dict) else {}

        log_provider_success(_NAME, model_id, latency_ms=latency_ms)
        return CompletionResponse(
            content=content,
            model_id=model_id,
            latency_ms=latency_ms,
            input_tokens=usage.get("promptTokenCount"),
            output_tokens=usage.get("candidatesTokenCount"),
        )

    async def health_check(self) -> bool:
        try:
            url = f"{self._base_url}/v1beta/models"
            response = await self._client.get(url)
            return response.status_code == 200
        except httpx.HTTPError:
            return False

    async def close(self) -> None:
        await self._client.aclose()
