"""Live integration test: LocalVerifierProvider against a SERVED verifier endpoint.

Skipped unless PRISM_LOCAL_VERIFIER_ENDPOINT is set (so CI stays hermetic). Proves the real path:
served Qwen3-14B groundedness soup -> provider re-template/strip/map -> prism's own
parse_citation_groundedness -> the correct citation outcome.

Run:  PRISM_LOCAL_VERIFIER_ENDPOINT=http://localhost:8092 pytest tests/integration/test_local_verifier_live.py
"""

import os

import pytest

from prism.core.citations import (
    build_citation_groundedness_prompts,
    parse_citation_groundedness,
)
from prism.providers.base import CompletionRequest
from prism.providers.local_verifier import LocalVerifierProvider

ENDPOINT = os.environ.get("PRISM_LOCAL_VERIFIER_ENDPOINT")
pytestmark = pytest.mark.skipif(
    not ENDPOINT, reason="set PRISM_LOCAL_VERIFIER_ENDPOINT to run the live verifier integration test"
)

_ABSTRACT = (
    "We introduce BERT, a deep bidirectional transformer. BERT obtains new state-of-the-art results on "
    "eleven NLP tasks, including pushing the GLUE score to 80.5% and SQuAD v1.1 test F1 to 93.2."
)

CASES = [
    # supported: the claim is a clean restatement of a fact in the abstract
    ("BERT achieves a GLUE score of 80.5%.", "BERT: Deep Bidirectional Transformers",
     _ABSTRACT, "supported"),
    # contradicted: the abstract states a different number
    ("BERT achieves a GLUE score of 70.5%.", "BERT: Deep Bidirectional Transformers",
     _ABSTRACT, "contradicted"),
    # not_addressed: the abstract is silent on training hardware
    ("BERT was trained on 16 TPU chips for four days.", "BERT: Deep Bidirectional Transformers",
     _ABSTRACT, "not_addressed"),
]


@pytest.mark.parametrize("claim,title,abstract,expected", CASES)
async def test_live_citation_outcome(claim, title, abstract, expected):
    provider = LocalVerifierProvider(ENDPOINT)
    system, user = build_citation_groundedness_prompts(claim, title, abstract)
    resp = await provider.complete(
        CompletionRequest(system_prompt=system, user_prompt=user, model_id="qwen3-14b-groundedness")
    )
    outcome, _span, _conf = parse_citation_groundedness(resp.content)
    assert outcome == expected, f"{claim!r} -> {outcome} (expected {expected})"
