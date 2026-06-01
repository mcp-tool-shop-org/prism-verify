"""Ollama model provider — local inference via HTTP API."""

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

DEFAULT_BASE_URL = "http://localhost:11434"


class OllamaProvider(ModelProvider):
    """Provider for local Ollama models."""

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        default_model: str = "mistral-small:24b",
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._default_model = default_model
        self._client = httpx.AsyncClient(base_url=self._base_url, timeout=30.0)

    @property
    def family(self) -> ModelFamily:
        return ModelFamily.LOCAL

    @property
    def available_models(self) -> list[str]:
        return [self._default_model]

    async def complete(self, request: CompletionRequest) -> CompletionResponse:
        model_id = request.model_id or self._default_model
        start = time.monotonic()

        try:
            response = await self._client.post(
                "/api/chat",
                json={
                    "model": model_id,
                    "messages": [
                        {"role": "system", "content": request.system_prompt},
                        {"role": "user", "content": request.user_prompt},
                    ],
                    "stream": False,
                    # format=json constrains decoding to a valid JSON object — the single
                    # biggest reliability win for local verdicts (Ollama uses XGrammar
                    # internally; constrained decoding is ~50% faster AND +3% accuracy,
                    # JSONSchemaBench arXiv:2501.10868). think=false keeps a thinking model
                    # from spending the num_predict budget on hidden reasoning and returning
                    # empty: Ollama's format zeroes non-compliant tokens INCLUDING <think>,
                    # so format+thinking are incompatible (ollama #10538). Pair with a
                    # NON-thinking instruct model (mistral-small:24b / granite4.1:30b return
                    # clean JSON; qwen3:32b returned empty — empirical v0.3 run).
                    "format": "json",
                    "think": False,
                    "options": {
                        "temperature": request.temperature,
                        "num_predict": request.max_tokens,
                    },
                },
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as e:
            raise ProviderError(
                f"Ollama API error: {e.response.status_code}",
                retryable=e.response.status_code >= 500,
            ) from e
        except httpx.ConnectError as e:
            raise ProviderError(
                f"Ollama not reachable at {self._base_url}", retryable=True
            ) from e

        latency_ms = int((time.monotonic() - start) * 1000)
        data = response.json()

        if isinstance(data, dict) and data.get("error"):
            raise ProviderError(f"Ollama API error: {data['error']}", retryable=False)
        message = data.get("message") if isinstance(data, dict) else None
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, str):
            raise ProviderError(
                "Ollama returned a malformed response (missing message.content)",
                retryable=False,
            )

        return CompletionResponse(
            content=content,
            model_id=model_id,
            latency_ms=latency_ms,
            input_tokens=data.get("prompt_eval_count"),
            output_tokens=data.get("eval_count"),
        )

    async def health_check(self) -> bool:
        try:
            response = await self._client.get("/api/tags")
            return response.status_code == 200
        except httpx.HTTPError:
            return False

    async def close(self) -> None:
        await self._client.aclose()
