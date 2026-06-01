"""Base lens protocol.

All lenses implement this protocol. A lens takes a stripped artifact + intent
and returns a LensResult via an alt-family model.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from prism.core.types import Artifact, LensResult

if TYPE_CHECKING:
    from prism.providers.base import ModelProvider


class Lens(ABC):
    """Abstract base for verification lenses."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique lens identifier (e.g., 'contract_completeness')."""
        ...

    @property
    @abstractmethod
    def description(self) -> str:
        """Human-readable description of what this lens checks."""
        ...

    @abstractmethod
    async def evaluate(
        self,
        artifact: Artifact,
        intent: str,
        model_family: str,
        model_id: str,
        provider: ModelProvider,
    ) -> LensResult:
        """Evaluate the artifact through this lens.

        Args:
            artifact: The (already-stripped) artifact to verify.
            intent: What the artifact is supposed to do.
            model_family: The verifier model family being used.
            model_id: The specific verifier model.
            provider: The model provider to call.

        Returns:
            LensResult with findings.
        """
        ...
