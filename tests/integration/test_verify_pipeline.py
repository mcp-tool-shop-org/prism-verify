"""End-to-end integration test for engine.verify() against mock providers (respx).

Exercises the full pipeline -- strip -> route -> fan-out 4 lenses -> rho -> aggregate ->
signed receipt -- and proves the lens_prompt_hashes PIN end-to-end.
"""

from __future__ import annotations

import asyncio
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
from prism.providers.base import (
    CompletionRequest,
    CompletionResponse,
    ModelProvider,
    ProviderError,
)
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
    router = FamilyRouter(
        routing_map={ModelFamily.ANTHROPIC: [(ModelFamily.LOCAL, "mistral-small:24b")]}
    )
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
    assert all(lr.model_id == "mistral-small:24b" for lr in result.lens_results)

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


async def test_strip_verification_failure_refuses_non_retryable(tmp_path, monkeypatch):
    """TEST-A-001: if reasoning survives stripping, verify() REFUSES (non-retryable) before any
    provider call — the security-critical refusal path (previously zero engine-level coverage).

    Neuter the strip patterns so a <thinking> tag survives the strip pass; _verify_strip then
    raises StripVerificationError, which the engine maps to STRIP_VERIFICATION_FAILED. Retrying
    cannot help (the artifact still carries reasoning), so retryable must be False.
    """
    import prism.core.stripping as stripping

    engine, store = _build_engine(tmp_path)
    monkeypatch.setattr(stripping, "_PATTERNS", [])  # strip pass is now a no-op

    request = VerifyRequest(
        artifact=Artifact(
            type=ArtifactType.CODE,
            content="def f():\n    return 1\n<thinking>secret plan</thinking>",
        ),
        intent="return one",
        caller=CallerContext(model_family=ModelFamily.ANTHROPIC, model_id="claude-x"),
    )
    with respx.mock(assert_all_called=False) as mock:
        # If the refusal works, NO provider call happens; assert_all_called=False tolerates that.
        route = mock.post(f"{OLLAMA_URL}/api/chat").mock(
            return_value=httpx.Response(200, json={"message": {"content": "{}"}})
        )
        result = await engine.verify(request)

    assert isinstance(result, VerifyError)
    assert result.reason == RefusalReason.STRIP_VERIFICATION_FAILED
    assert result.retryable is False
    assert route.call_count == 0  # refused before fan-out — no provider was touched
    store.close()


def test_local_route_id_matches_ollama_default():
    """Guards the routing-map <-> provider drift the audit found (qwen3-32b vs qwen3:32b)."""
    local_ids = {
        model_id
        for routes in DEFAULT_ROUTING_MAP.values()
        for family, model_id in routes
        if family == ModelFamily.LOCAL
    }
    assert local_ids == {"mistral-small:24b"}  # must match OllamaProvider's default model


class _SlowProvider(ModelProvider):
    """A local provider that sleeps longer than a tight latency budget.

    Records how many calls ENTERED (before the sleep) and how many COMPLETED (after the sleep),
    so a test can prove the in-flight lens tasks were cancelled at the budget ceiling — TEST-A-007.
    """

    def __init__(self) -> None:
        self.entered = 0
        self.completed = 0

    @property
    def family(self) -> ModelFamily:
        return ModelFamily.LOCAL

    @property
    def available_models(self) -> list[str]:
        return ["slow-local"]

    async def complete(self, request: CompletionRequest) -> CompletionResponse:
        self.entered += 1
        await asyncio.sleep(0.2)
        # Reached ONLY if the task was not cancelled at the budget ceiling.
        self.completed += 1
        return CompletionResponse(
            content='{"outcome": "pass", "confidence": 0.9, "findings": []}',
            model_id="slow-local",
            latency_ms=200,
        )

    async def health_check(self) -> bool:
        return True


async def test_budget_exceeded_when_fanout_outruns_latency_budget(tmp_path):
    engine, store = _build_engine(tmp_path)
    engine._providers["local"] = _SlowProvider()
    request = _request()
    # Drive the budget below the 1000ms constructor floor for a fast deterministic test
    # (assignment validation is off, so this bypasses the ge=1000 bound).
    request.budget.max_latency_ms = 50

    result = await engine.verify(request)
    assert isinstance(result, VerifyError)
    assert result.reason == RefusalReason.BUDGET_EXCEEDED
    assert result.retryable is True
    store.close()


async def test_budget_exceeded_cancels_inflight_lens_tasks(tmp_path):
    """TEST-A-007: after a BUDGET_EXCEEDED return, the in-flight lens tasks are CANCELLED — the
    slow provider entered but never completed, proving no leaked task / double-spend continues
    running (and being billed) past the latency ceiling."""
    engine, store = _build_engine(tmp_path)
    slow = _SlowProvider()
    engine._providers["local"] = slow
    request = _request()
    request.budget.max_latency_ms = 50  # well under the provider's 200ms sleep

    result = await engine.verify(request)
    assert isinstance(result, VerifyError)
    assert result.reason == RefusalReason.BUDGET_EXCEEDED
    assert slow.entered > 0  # lenses did start (the fan-out ran)
    assert slow.completed == 0  # ...but every in-flight call was cancelled at the ceiling

    # Give any (incorrectly) un-cancelled task a chance to finish past the budget; if cancellation
    # were broken, completed would tick up here. It must stay 0 — the tasks are truly dead.
    await asyncio.sleep(0.3)
    assert slow.completed == 0
    store.close()


class _PartialErrorProvider(ModelProvider):
    """Errors on the first ``error_count`` calls, returns a PASS for the rest.

    The verdict depends only on HOW MANY lenses error (not which), so a call-count gate gives a
    deterministic genuine/errored split despite the nondeterministic parallel fan-out order.
    """

    def __init__(self, error_count: int) -> None:
        self._remaining_errors = error_count

    @property
    def family(self) -> ModelFamily:
        return ModelFamily.LOCAL

    @property
    def available_models(self) -> list[str]:
        return ["mistral-small:24b"]

    async def complete(self, request: CompletionRequest) -> CompletionResponse:
        # asyncio is single-threaded, so this counter needs no lock.
        if self._remaining_errors > 0:
            self._remaining_errors -= 1
            raise ProviderError("simulated provider outage", retryable=True)
        return CompletionResponse(
            content='{"outcome": "pass", "confidence": 0.95, "findings": []}',
            model_id="mistral-small:24b",
            latency_ms=5,
        )

    async def health_check(self) -> bool:
        return True


async def test_three_genuine_pass_with_one_errored_lens_accepts(tmp_path):
    """TEST-A-002: 3 lenses PASS genuinely + a 4th hits a ProviderError → ACCEPT.

    The errored lens is an availability fault, EXCLUDED from aggregation; with 3 genuine PASS
    results (>= MIN_LENSES) the verdict is ACCEPT, not ESCALATE — a single transient blip must
    not silently force a human escalation."""
    engine, store = _build_engine(tmp_path)
    engine._providers["local"] = _PartialErrorProvider(error_count=1)

    result = await engine.verify(_request())
    assert isinstance(result, VerifyResponse)
    assert result.verdict == Verdict.ACCEPT
    assert len(result.lens_results) == 4  # all four recorded (incl. the errored placeholder)
    assert sum(1 for lr in result.lens_results if lr.errored) == 1
    assert sum(1 for lr in result.lens_results if not lr.errored) == 3
    store.close()


async def test_two_of_four_errored_is_verifier_unavailable(tmp_path):
    """TEST-A-002 (other side of the split): with only 2 genuine results (< MIN_LENSES=3) the
    engine returns VERIFIER_UNAVAILABLE (retryable), NOT a verdict and NOT a lens collapse —
    too few independent signals is an availability fault."""
    from prism.core.engine import MIN_LENSES

    assert MIN_LENSES == 3  # the split pins to this floor
    engine, store = _build_engine(tmp_path)
    engine._providers["local"] = _PartialErrorProvider(error_count=2)  # 2 errored, 2 genuine

    result = await engine.verify(_request())
    assert isinstance(result, VerifyError)
    assert result.reason == RefusalReason.VERIFIER_UNAVAILABLE
    assert result.retryable is True
    store.close()


async def test_harvest_sink_fires_through_real_verify_when_enabled(tmp_path, monkeypatch):
    """The opt-in L4 sink fires end-to-end: a groundedness PASS becomes one 'supported' record,
    joined to the real receipt by receipt_id. The other three lenses are not 'groundedness' and
    contribute nothing — the name filter holds through the real pipeline (prism.eval.harvest).
    """
    harvest_file = tmp_path / "harvest.jsonl"
    monkeypatch.setenv("PRISM_HARVEST_PATH", str(harvest_file))
    engine, store = _build_engine(tmp_path)
    lens_json = json.dumps({"outcome": "pass", "confidence": 0.95, "findings": []})
    with respx.mock(assert_all_called=False) as mock:
        mock.post(f"{OLLAMA_URL}/api/chat").mock(
            return_value=httpx.Response(200, json={"message": {"content": lens_json}})
        )
        result = await engine.verify(_request())

    assert isinstance(result, VerifyResponse)
    lines = harvest_file.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1  # only the groundedness lens contributes
    rec = json.loads(lines[0])
    assert rec["schema"] == "prism-l4-harvest/v1"
    assert rec["source"] == "prism-groundedness"
    assert rec["verdict"] == "supported"
    assert rec["receipt_id"] == result.receipt.id  # the join key holds end-to-end
    store.close()


async def test_harvest_sink_is_off_by_default(tmp_path, monkeypatch):
    """Default-off: with no PRISM_HARVEST_PATH, a full verify writes no harvest file at all."""
    monkeypatch.delenv("PRISM_HARVEST_PATH", raising=False)
    engine, store = _build_engine(tmp_path)
    lens_json = json.dumps({"outcome": "pass", "confidence": 0.95, "findings": []})
    with respx.mock(assert_all_called=False) as mock:
        mock.post(f"{OLLAMA_URL}/api/chat").mock(
            return_value=httpx.Response(200, json={"message": {"content": lens_json}})
        )
        result = await engine.verify(_request())

    assert isinstance(result, VerifyResponse)
    assert not (tmp_path / "harvest.jsonl").exists()
    store.close()
