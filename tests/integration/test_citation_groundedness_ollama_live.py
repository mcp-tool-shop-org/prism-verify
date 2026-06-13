"""Live integration test: the citation-groundedness lens against a local OLLAMA model.

Skipped unless PRISM_OLLAMA_LIVE=1 (so CI stays hermetic). Proves the EXTERNAL_VERIFIER path that
role-os's `verify-citations --provider ollama` actually runs: a different-family (LOCAL, not the
anthropic caller), reasoning-stripped model judges a CLAIM against a retrieved SOURCE and returns a
real SUPPORTED / CONTRADICTED / NOT_ADDRESSED verdict — not a silent not_addressed.

Run against a live Ollama (a non-thinking instruct model returns clean JSON under format=json;
mistral-small:24b / granite4.1:30b are known-good — qwen3:32b returns empty):
  PRISM_OLLAMA_LIVE=1 PRISM_OLLAMA_MODEL=mistral-small:24b \
    pytest tests/integration/test_citation_groundedness_ollama_live.py
"""

import os

import pytest

from prism.core.citations import (
    build_citation_groundedness_prompts,
    parse_citation_groundedness,
)
from prism.providers.base import CompletionRequest
from prism.providers.ollama import OllamaProvider

pytestmark = pytest.mark.skipif(
    os.environ.get("PRISM_OLLAMA_LIVE") != "1",
    reason="set PRISM_OLLAMA_LIVE=1 (and have Ollama serving PRISM_OLLAMA_MODEL) to run this",
)

MODEL = os.environ.get("PRISM_OLLAMA_MODEL", "mistral-small:24b")

_TITLE = "Attention Is All You Need"
_ABSTRACT = (
    "We propose a new simple network architecture, the Transformer, based solely on attention "
    "mechanisms, dispensing with recurrence and convolutions entirely. Experiments on two machine "
    "translation tasks show these models to be superior in quality while being more parallelizable "
    "and requiring significantly less time to train."
)

CASES = [
    # known-good: a faithful restatement of the abstract -> SUPPORTED
    (
        "The Transformer is a network architecture based solely on attention mechanisms, "
        "dispensing with recurrence and convolutions entirely.",
        "supported",
    ),
    # deliberately mismatched: the abstract says the OPPOSITE -> NOT_SUPPORTED (contradicted)
    (
        "The Transformer relies heavily on recurrent and convolutional layers to achieve its results.",
        "contradicted",
    ),
    # orthogonal claim the abstract is silent on -> NOT_SUPPORTED (not_addressed, not a fabrication)
    (
        "The Transformer was trained on 64 TPU v3 chips for two weeks.",
        "not_addressed",
    ),
]


@pytest.mark.parametrize("claim,expected", CASES)
async def test_live_groundedness_outcome(claim, expected):
    provider = OllamaProvider(default_model=MODEL)
    try:
        system, user = build_citation_groundedness_prompts(claim, _TITLE, _ABSTRACT)
        resp = await provider.complete(
            CompletionRequest(system_prompt=system, user_prompt=user, model_id=MODEL)
        )
    finally:
        await provider.close()
    outcome, _span, _conf = parse_citation_groundedness(resp.content)
    # A known-good claim must be SUPPORTED; a mismatched/orthogonal claim must be NOT_SUPPORTED
    # (contradicted or not_addressed) — never a false SUPPORTED on a claim the source does not back.
    if expected == "supported":
        assert outcome == "supported", f"{claim!r} -> {outcome} (expected supported)"
    else:
        assert outcome != "supported", f"{claim!r} -> {outcome} (must not be a false SUPPORTED)"
