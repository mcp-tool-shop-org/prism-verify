"""Shared engine construction for the CLI / MCP / HTTP surfaces.

One place builds the default lens set + the provider map from the environment, so the three
transports cannot drift apart (the family-of-call-sites lesson). Each surface is a thin wrapper
over the engine this returns.
"""

from __future__ import annotations

import os

from prism.core.engine import VerificationEngine
from prism.lenses.boundary import CrossBoundaryLens
from prism.lenses.contract import ContractCompletenessLens
from prism.lenses.groundedness import GroundednessLens
from prism.lenses.invariant import InvariantLens
from prism.lenses.registry import register_lens
from prism.providers.base import ModelProvider


def register_default_lenses() -> None:
    """Register the v1 four-lens set (idempotent enough — registry de-dupes by name)."""
    register_lens(ContractCompletenessLens())
    register_lens(CrossBoundaryLens())
    register_lens(InvariantLens())
    register_lens(GroundednessLens())


def build_providers_from_env() -> dict[str, ModelProvider]:
    """Build the provider map: always-on local Ollama + any hosted family with an API key set."""
    providers: dict[str, ModelProvider] = {}

    from prism.providers.ollama import OllamaProvider

    providers["local"] = OllamaProvider()

    anthropic_key = os.environ.get("ANTHROPIC_API_KEY")
    if anthropic_key:
        from prism.providers.anthropic import AnthropicProvider

        providers["anthropic"] = AnthropicProvider(api_key=anthropic_key)

    openai_key = os.environ.get("OPENAI_API_KEY")
    if openai_key:
        from prism.providers.openai import OpenAIProvider

        providers["openai"] = OpenAIProvider(api_key=openai_key)

    google_key = os.environ.get("GOOGLE_API_KEY")
    if google_key:
        from prism.providers.google import GoogleProvider

        providers["google"] = GoogleProvider(api_key=google_key)

    return providers


def build_default_engine() -> VerificationEngine:
    """Register the default lenses and construct an engine with env-configured providers."""
    register_default_lenses()
    return VerificationEngine(providers=build_providers_from_env())
