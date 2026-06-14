"""Base model provider protocol."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass

from prism.core.types import ModelFamily

try:
    from prism.core.observability import get_request_id
except ImportError:  # pragma: no cover - cross-module bootstrap fallback only
    def get_request_id() -> str:
        return "-"

# Shared parent logger for all six adapters. Per-adapter calls pass the provider name as a field
# (``provider=``) so a single ``prism.providers`` grep surfaces every adapter's failures with the
# same shape; child loggers (``prism.providers.<name>``) inherit this and stay greppable too.
logger = logging.getLogger("prism.providers")


def log_provider_failure(
    provider: str,
    model_id: str,
    exc: BaseException,
    *,
    latency_ms: int,
    status: int | None = None,
) -> None:
    """Emit one consistent WARNING for a failed provider call (PRV-B-001).

    Fields are uniform across all six adapters so a partial outage is greppable instead of
    invisible until it surfaces as VERIFIER_UNAVAILABLE. NEVER logs the API key, auth header,
    or any prompt/artifact content — only the model id, HTTP status (if any), latency, exception
    type, and the current request id.
    """
    logger.warning(
        "provider call failed",
        extra={
            "provider": provider,
            "model_id": model_id,
            "http_status": status,
            "latency_ms": latency_ms,
            "exc_type": type(exc).__name__,
            "request_id": get_request_id(),
        },
    )


def log_provider_success(provider: str, model_id: str, *, latency_ms: int) -> None:
    """Emit a quiet DEBUG on a successful provider call (model + latency).

    DEBUG, not INFO: success latency is already measured and returned on the response, so surfacing
    it at INFO would be per-call spam. Kept consistent with the failure shape for greppability.
    """
    logger.debug(
        "provider call ok",
        extra={
            "provider": provider,
            "model_id": model_id,
            "latency_ms": latency_ms,
            "request_id": get_request_id(),
        },
    )


@dataclass
class CompletionRequest:
    """Request to a model provider."""

    system_prompt: str
    user_prompt: str
    model_id: str
    max_tokens: int = 2000
    temperature: float = 0.0


@dataclass
class CompletionResponse:
    """Response from a model provider."""

    content: str
    model_id: str
    latency_ms: int
    input_tokens: int | None = None
    output_tokens: int | None = None


class ModelProvider(ABC):
    """Abstract base for model providers."""

    @property
    @abstractmethod
    def family(self) -> ModelFamily:
        """The model family this provider serves."""
        ...

    @property
    @abstractmethod
    def available_models(self) -> list[str]:
        """List of model IDs this provider can serve."""
        ...

    @abstractmethod
    async def complete(self, request: CompletionRequest) -> CompletionResponse:
        """Send a completion request to the model.

        Raises:
            ProviderError: If the request fails.
        """
        ...

    @abstractmethod
    async def health_check(self) -> bool:
        """Check if the provider is reachable."""
        ...


class ProviderError(Exception):
    """Raised when a provider call fails."""

    def __init__(self, message: str, *, retryable: bool = True) -> None:
        self.retryable = retryable
        super().__init__(message)
