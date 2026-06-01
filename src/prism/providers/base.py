"""Base model provider protocol."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from prism.core.types import ModelFamily


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
