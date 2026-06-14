"""Tests for verdict aggregation (engine.aggregate_verdict) and the engine<->breaker interaction.

Pins the conservative ordering and the two audit-surfaced bugs: a FAIL with only
minor/empty findings must not become ACCEPT, and a mixed PASS+UNCERTAIN must ESCALATE
rather than silently ACCEPT. Plus CORE-A-001: a verifier that fails a MINORITY of lenses every
request must NOT have its circuit-breaker reset by an unconditional request-level report_success.
"""

from __future__ import annotations

from prism.core.engine import VerificationEngine, aggregate_verdict
from prism.core.routing import CIRCUIT_BREAKER_THRESHOLD, FamilyRouter
from prism.core.types import (
    Artifact,
    ArtifactType,
    CallerContext,
    Finding,
    LensOutcome,
    LensResult,
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
from prism.receipts.store import ReceiptStore


def _lr(outcome: LensOutcome, *, findings=None, confidence: float = 0.9) -> LensResult:
    return LensResult(
        lens="x",
        model_family="google",
        model_id="g",
        outcome=outcome,
        findings=findings or [],
        confidence=confidence,
    )


def _fail(severity: str) -> LensResult:
    return _lr(LensOutcome.FAIL, findings=[Finding(category="c", evidence="e", severity=severity)])


class TestAggregateVerdict:
    def test_all_pass_is_accept(self) -> None:
        verdict, _, _ = aggregate_verdict([_lr(LensOutcome.PASS)] * 3)
        assert verdict == Verdict.ACCEPT

    def test_pass_plus_uncertain_escalates_not_accepts(self) -> None:
        # Headline bug: mixed PASS + UNCERTAIN previously collapsed to ACCEPT.
        results = [_lr(LensOutcome.PASS), _lr(LensOutcome.PASS), _lr(LensOutcome.UNCERTAIN)]
        verdict, _, _ = aggregate_verdict(results)
        assert verdict == Verdict.ESCALATE

    def test_all_uncertain_escalates(self) -> None:
        verdict, _, _ = aggregate_verdict([_lr(LensOutcome.UNCERTAIN)] * 3)
        assert verdict == Verdict.ESCALATE

    def test_fail_with_minor_finding_is_revise_not_accept(self) -> None:
        # Audit bug: a FAIL whose findings are all minor used to fall through to ACCEPT.
        results = [_lr(LensOutcome.PASS), _lr(LensOutcome.PASS), _fail("minor")]
        verdict, _, retryable = aggregate_verdict(results)
        assert verdict == Verdict.REVISE
        assert retryable is True

    def test_fail_with_no_findings_is_revise(self) -> None:
        verdict, _, _ = aggregate_verdict([_lr(LensOutcome.PASS), _lr(LensOutcome.FAIL)])
        assert verdict == Verdict.REVISE

    def test_fail_with_critical_is_refuse(self) -> None:
        verdict, _, retryable = aggregate_verdict([_lr(LensOutcome.PASS), _fail("critical")])
        assert verdict == Verdict.REFUSE
        assert retryable is False

    def test_fail_major_is_revise(self) -> None:
        verdict, _, _ = aggregate_verdict([_fail("major"), _lr(LensOutcome.PASS)])
        assert verdict == Verdict.REVISE

    def test_fail_precedes_uncertain(self) -> None:
        # A concrete FAIL is more actionable than uncertainty.
        verdict, _, _ = aggregate_verdict([_fail("major"), _lr(LensOutcome.UNCERTAIN)])
        assert verdict == Verdict.REVISE

    def test_confidence_is_minimum(self) -> None:
        results = [_lr(LensOutcome.PASS, confidence=0.9), _lr(LensOutcome.PASS, confidence=0.4)]
        _, confidence, _ = aggregate_verdict(results)
        assert confidence == 0.4


# --- CORE-A-001: engine <-> circuit-breaker interaction -----------------------------------------


class _MinorityErrorProvider(ModelProvider):
    """One configured verifier whose FIRST call each request raises (a minority lens fault), and the
    rest PASS. Across the 4-lens fan-out that is 1 errored + 3 genuine PASS -> the request still
    ACCEPTs, but a real provider fault occurred this request."""

    def __init__(self) -> None:
        self.calls = 0
        self._errored_this_request = False

    @property
    def family(self) -> ModelFamily:
        return ModelFamily.LOCAL

    @property
    def available_models(self) -> list[str]:
        return ["mistral-small:24b"]

    def start_request(self) -> None:
        self._errored_this_request = False

    async def complete(self, request: CompletionRequest) -> CompletionResponse:
        self.calls += 1
        # Exactly one fault per request (the parallel fan-out order does not matter to the count).
        if not self._errored_this_request:
            self._errored_this_request = True
            raise ProviderError("simulated minority lens fault", retryable=True)
        return CompletionResponse(
            content='{"outcome": "pass", "confidence": 0.95, "findings": []}',
            model_id="mistral-small:24b",
            latency_ms=1,
        )

    async def health_check(self) -> bool:
        return True


class _SpyRouter(FamilyRouter):
    """A router that records report_success / report_failure calls per (family, model_id)."""

    def __init__(self, routing_map) -> None:
        super().__init__(routing_map=routing_map)
        self.successes: list[tuple[str, str]] = []
        self.failures: list[tuple[str, str]] = []

    def report_success(self, family, model_id) -> None:
        self.successes.append((family.value, model_id))
        super().report_success(family, model_id)

    def report_failure(self, family, model_id) -> None:
        self.failures.append((family.value, model_id))
        super().report_failure(family, model_id)


def _register_v1_lenses() -> None:
    register_lens(ContractCompletenessLens())
    register_lens(CrossBoundaryLens())
    register_lens(InvariantLens())
    register_lens(GroundednessLens())


def _code_request() -> VerifyRequest:
    return VerifyRequest(
        artifact=Artifact(type=ArtifactType.CODE, content="def add(a, b):\n    return a + b\n"),
        intent="Add two integers and return the sum.",
        caller=CallerContext(model_family=ModelFamily.ANTHROPIC, model_id="claude-x"),
    )


class TestCircuitBreakerGenuineResultFloor:
    """CORE-A-001: a minority lens fault each request must NOT be wiped by report_success."""

    def _engine(self) -> tuple[VerificationEngine, _SpyRouter, _MinorityErrorProvider]:
        _register_v1_lenses()
        router = _SpyRouter(
            routing_map={ModelFamily.ANTHROPIC: [(ModelFamily.LOCAL, "mistral-small:24b")]}
        )
        provider = _MinorityErrorProvider()
        engine = VerificationEngine(
            providers={"local": provider},
            router=router,
            receipt_store=ReceiptStore(signing_secret=b"core-a-001"),
        )
        return engine, router, provider

    async def _verify_once(self, engine, provider):
        provider.start_request()
        return await engine.verify(_code_request())

    async def test_report_success_not_called_when_a_lens_errors(self):
        engine, router, provider = self._engine()
        result = await self._verify_once(engine, provider)
        # The request still ACCEPTs (3 genuine PASS >= MIN_LENSES), but a fault occurred...
        assert isinstance(result, VerifyResponse)
        assert result.verdict == Verdict.ACCEPT
        assert sum(1 for lr in result.lens_results if lr.errored) == 1
        # ...so the engine must NOT report success for this provider (it would clear the failure
        # the errored lens already recorded). report_failure DID fire for the fault.
        assert ("local", "mistral-small:24b") not in router.successes
        assert ("local", "mistral-small:24b") in router.failures

    async def test_breaker_trips_after_enough_minority_failure_requests(self):
        engine, router, provider = self._engine()
        # Each request records exactly one failure and (post-fix) NO success, so after
        # CIRCUIT_BREAKER_THRESHOLD requests the breaker opens. Under the old unconditional
        # report_success the failures were wiped every request and the breaker never tripped.
        for _ in range(CIRCUIT_BREAKER_THRESHOLD):
            await self._verify_once(engine, provider)
        circuit = router._get_circuit("local:mistral-small:24b")
        assert circuit.is_open is True
        assert router.successes == []  # success was never reported across all faulting requests


# --- CORE-B-001: sycophancy single-lens path <-> circuit-breaker -------------------------------


class _AlwaysErrorSycophancyProvider(ModelProvider):
    """A LOCAL_SYCOPHANCY specialist whose every call raises — a flapping specialist."""

    def __init__(self) -> None:
        self.calls = 0

    @property
    def family(self) -> ModelFamily:
        return ModelFamily.LOCAL_SYCOPHANCY

    @property
    def available_models(self) -> list[str]:
        return ["sycophancy-14b-soup"]

    async def complete(self, request: CompletionRequest) -> CompletionResponse:
        self.calls += 1
        raise ProviderError("simulated sycophancy specialist fault", retryable=True)

    async def health_check(self) -> bool:
        return True


class _CleanSycophancyProvider(ModelProvider):
    """A LOCAL_SYCOPHANCY specialist that returns a genuine non-errored 'pass' every call."""

    @property
    def family(self) -> ModelFamily:
        return ModelFamily.LOCAL_SYCOPHANCY

    @property
    def available_models(self) -> list[str]:
        return ["sycophancy-14b-soup"]

    async def complete(self, request: CompletionRequest) -> CompletionResponse:
        return CompletionResponse(
            content='{"outcome": "pass", "confidence": 0.95, "findings": []}',
            model_id="sycophancy-14b-soup",
            latency_ms=1,
        )

    async def health_check(self) -> bool:
        return True


def _response_request() -> VerifyRequest:
    # A RESPONSE artifact routes to the sycophancy path; with only the specialist configured the
    # engine takes the single-lens path (< MIN_LENSES disjoint families).
    return VerifyRequest(
        artifact=Artifact(type=ArtifactType.RESPONSE, content="Yes, you're totally right!"),
        intent="The Earth is flat, right?",
        caller=CallerContext(model_family=ModelFamily.OPENAI, model_id="producer"),
    )


class TestSycophancySingleBreaker:
    """CORE-B-001: the single sycophancy path wires the breaker — a flapping specialist trips."""

    def _engine(self, provider: ModelProvider) -> tuple[VerificationEngine, _SpyRouter]:
        router = _SpyRouter(routing_map={})
        engine = VerificationEngine(
            providers={"local-sycophancy": provider},
            router=router,
            receipt_store=ReceiptStore(signing_secret=b"core-b-001"),
        )
        return engine, router

    async def test_error_reports_failure_and_trips_breaker(self):
        provider = _AlwaysErrorSycophancyProvider()
        engine, router = self._engine(provider)
        key = "local-sycophancy:sycophancy-14b-soup"
        for _ in range(CIRCUIT_BREAKER_THRESHOLD):
            result = await engine.verify(_response_request())
            assert isinstance(result, VerifyError)
            assert result.reason == RefusalReason.VERIFIER_UNAVAILABLE
        # Each erroring request reported a failure; none reported success -> breaker OPEN.
        assert router.failures.count(("local-sycophancy", "sycophancy-14b-soup")) == (
            CIRCUIT_BREAKER_THRESHOLD
        )
        assert ("local-sycophancy", "sycophancy-14b-soup") not in router.successes
        assert router._get_circuit(key).is_open is True

    async def test_genuine_result_reports_success(self):
        provider = _CleanSycophancyProvider()
        engine, router = self._engine(provider)
        result = await engine.verify(_response_request())
        assert isinstance(result, VerifyResponse)
        assert result.verdict == Verdict.ACCEPT
        # A clean genuine adjudication reports success (genuine-result floor), not failure.
        assert ("local-sycophancy", "sycophancy-14b-soup") in router.successes
        assert ("local-sycophancy", "sycophancy-14b-soup") not in router.failures


# --- CORE-B-003: receipt-builder dedup is behavior-identical ------------------------------------


class TestReceiptBuilderDedup:
    """The extracted _build_and_store_receipt produces a VALIDLY SIGNED receipt on each path.

    The byte-identity of the signed field-set is proven by the existing receipt/signature tests
    (test_verify_pipeline.py + test_sycophancy_panel_engine.py) still passing after the extraction;
    this adds a direct check that the single helper signs a verifiable receipt for the code path.
    """

    async def test_code_path_receipt_verifies_via_shared_builder(self):
        _register_v1_lenses()
        router = _SpyRouter(
            routing_map={ModelFamily.ANTHROPIC: [(ModelFamily.LOCAL, "mistral-small:24b")]}
        )
        engine = VerificationEngine(
            providers={"local": _CleanCodeProvider()},
            router=router,
            receipt_store=ReceiptStore(signing_secret=b"core-b-003"),
        )
        result = await engine.verify(_code_request())
        assert isinstance(result, VerifyResponse)
        # The receipt built by the shared helper verifies against the store (signed field-set
        # intact) and its lens_prompt_hashes match the comprehension contract (no dropped hash).
        assert engine._receipt_store.verify_signature(result.receipt.id) is True
        expected_hashes = {
            lr.lens: lr.prompt_hash
            for lr in result.lens_results
            if lr.prompt_hash is not None
        }
        assert result.receipt.lens_prompt_hashes == expected_hashes


class _CleanCodeProvider(ModelProvider):
    """A LOCAL verifier that PASSES every lens (for receipt-builder invariance on the code path)."""

    @property
    def family(self) -> ModelFamily:
        return ModelFamily.LOCAL

    @property
    def available_models(self) -> list[str]:
        return ["mistral-small:24b"]

    async def complete(self, request: CompletionRequest) -> CompletionResponse:
        return CompletionResponse(
            content='{"outcome": "pass", "confidence": 0.95, "findings": []}',
            model_id="mistral-small:24b",
            latency_ms=1,
        )

    async def health_check(self) -> bool:
        return True
