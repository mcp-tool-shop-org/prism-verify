"""End-to-end integration test for engine.verify() against mock providers (respx).

Exercises the full pipeline -- strip -> route -> fan-out 4 lenses -> rho -> aggregate ->
signed receipt -- and proves the lens_prompt_hashes PIN end-to-end.
"""

from __future__ import annotations

import json

import httpx
import respx

from prism.core.engine import VerificationEngine
from prism.core.routing import DEFAULT_ROUTING_MAP, FamilyRouter
from prism.core.types import (
    Artifact,
    ArtifactType,
    CallerContext,
    ModelFamily,
    RefusalReason,
    Verdict,
    VerifyError,
    VerifyRequest,
    VerifyResponse,
)
from prism.lenses.boundary import CrossBoundaryLens
from prism.lenses.contract import ContractCompletenessLens
from prism.lenses.groundedness import GroundednessLens
from prism.lenses.invariant import InvariantLens
from prism.lenses.registry import register_lens
from prism.providers.ollama import OllamaProvider
from prism.receipts.store import ReceiptStore

OLLAMA_URL = "http://test-ollama"


def _build_engine(tmp_path) -> tuple[VerificationEngine, ReceiptStore]:
    # Register the four v1 lenses (the conftest autouse fixture clears the registry first).
    register_lens(ContractCompletenessLens())
    register_lens(CrossBoundaryLens())
    register_lens(InvariantLens())
    register_lens(GroundednessLens())
    # Route an Anthropic-family caller to a LOCAL (Ollama) verifier so we can mock the HTTP.
    router = FamilyRouter(routing_map={ModelFamily.ANTHROPIC: [(ModelFamily.LOCAL, "qwen3:32b")]})
    store = ReceiptStore(db_path=tmp_path / "receipts.db", signing_secret=b"integration-secret")
    engine = VerificationEngine(
        providers={"local": OllamaProvider(base_url=OLLAMA_URL)},
        router=router,
        receipt_store=store,
    )
    return engine, store


def _request() -> VerifyRequest:
    return VerifyRequest(
        artifact=Artifact(type=ArtifactType.CODE, content="def add(a, b):\n    return a + b\n"),
        intent="Add two integers and return the sum.",
        caller=CallerContext(model_family=ModelFamily.ANTHROPIC, model_id="claude-x"),
    )


async def test_full_pipeline_accept_signs_receipt_with_pin(tmp_path):
    engine, store = _build_engine(tmp_path)
    lens_json = json.dumps({"outcome": "pass", "confidence": 0.95, "findings": []})
    with respx.mock(assert_all_called=False) as mock:
        route = mock.post(f"{OLLAMA_URL}/api/chat").mock(
            return_value=httpx.Response(200, json={"message": {"content": lens_json}})
        )
        result = await engine.verify(_request())

    assert isinstance(result, VerifyResponse)
    assert result.verdict == Verdict.ACCEPT
    assert route.call_count == 4  # one call per lens
    assert len(result.lens_results) == 4
    assert all(lr.outcome.value == "pass" for lr in result.lens_results)
    assert all(not lr.errored for lr in result.lens_results)
    assert all(lr.model_id == "qwen3:32b" for lr in result.lens_results)

    # PIN proven end-to-end: a SHA-256 prompt hash per lens, persisted AND signed.
    hashes = result.receipt.lens_prompt_hashes
    assert len(hashes) == 4
    assert all(len(h) == 64 and set(h) <= set("0123456789abcdef") for h in hashes.values())
    assert store.verify_signature(result.receipt.id) is True
    store.close()


async def test_provider_outage_is_verifier_unavailable_not_lens_collapse(tmp_path):
    engine, store = _build_engine(tmp_path)
    with respx.mock(assert_all_called=False) as mock:
        mock.post(f"{OLLAMA_URL}/api/chat").mock(return_value=httpx.Response(503))
        result = await engine.verify(_request())

    # Every lens hit the same 503; that is an availability fault, not a lens collapse.
    assert isinstance(result, VerifyError)
    assert result.reason == RefusalReason.VERIFIER_UNAVAILABLE
    assert result.retryable is True
    store.close()


def test_local_route_id_matches_ollama_default():
    """Guards the routing-map <-> provider drift the audit found (qwen3-32b vs qwen3:32b)."""
    local_ids = {
        model_id
        for routes in DEFAULT_ROUTING_MAP.values()
        for family, model_id in routes
        if family == ModelFamily.LOCAL
    }
    assert local_ids == {"qwen3:32b"}  # must match OllamaProvider's default model
