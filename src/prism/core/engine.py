"""Core verification engine.

Orchestrates: strip -> route -> fan-out lenses -> rho check -> aggregate -> receipt.
This is the main verify() entrypoint that everything else wraps (CLI, MCP, HTTP).
"""

from __future__ import annotations

import asyncio
import json

from prism.core.routing import FamilyRouter, RouteSelection, RoutingError
from prism.core.stripping import StripVerificationError, strip_reasoning
from prism.core.submodularity import compute_pairwise_rho
from prism.core.types import (
    Artifact,
    Finding,
    LensOutcome,
    LensResult,
    RefusalReason,
    Verdict,
    VerifyError,
    VerifyRequest,
    VerifyResponse,
)
from prism.lenses.base import Lens, compute_prompt_hash
from prism.lenses.registry import resolve_lenses
from prism.providers.base import ModelProvider, ProviderError
from prism.receipts.store import ReceiptStore

# Minimum lenses required (Lock 3)
MIN_LENSES = 3


def aggregate_verdict(lens_results: list[LensResult]) -> tuple[Verdict, float, bool]:
    """Aggregate genuine (non-errored) lens results into a verdict.

    Conservative ordering:
      - any FAIL with a critical finding -> REFUSE (non-retryable)
      - any FAIL                          -> REVISE (retryable); an explicit FAIL is
        authoritative, so finding severity may escalate it to REFUSE but never nullify it
      - any UNCERTAIN                     -> ESCALATE (route to a human)
      - all PASS                          -> ACCEPT

    Callers pass only genuine results; provider/parse faults are handled upstream as an
    availability refusal, so a single transient blip never silently forces an escalation.
    """
    has_critical = False
    has_fail = False
    has_uncertain = False
    confidences: list[float] = []
    for lr in lens_results:
        confidences.append(lr.confidence)
        if lr.outcome == LensOutcome.FAIL:
            has_fail = True
            if any(f.severity == "critical" for f in lr.findings):
                has_critical = True
        elif lr.outcome == LensOutcome.UNCERTAIN:
            has_uncertain = True

    confidence = min(confidences) if confidences else 0.0
    if has_critical:
        return Verdict.REFUSE, confidence, False
    if has_fail:
        return Verdict.REVISE, confidence, True
    if has_uncertain:
        return Verdict.ESCALATE, confidence, False
    return Verdict.ACCEPT, confidence, False


class VerificationEngine:
    """Core engine that executes the full verification pipeline."""

    def __init__(
        self,
        providers: dict[str, ModelProvider],
        router: FamilyRouter | None = None,
        receipt_store: ReceiptStore | None = None,
    ) -> None:
        self._providers = providers
        self._router = router or FamilyRouter()
        self._receipt_store = receipt_store or ReceiptStore()

    async def verify(self, request: VerifyRequest) -> VerifyResponse | VerifyError:
        """Execute the full verification pipeline.

        Steps:
        1. STRIP reasoning from artifact
        2. ROUTE to alt-family verifier
        3. FAN-OUT lenses in parallel
        4. SPLIT genuine adjudications from provider/parse faults
        5. RHO check (submodularity) over genuine results
        6. AGGREGATE verdict over genuine results
        7. RECEIPT generation
        """
        # Step 1: Strip reasoning
        try:
            strip_result = strip_reasoning(request.artifact.content)
        except StripVerificationError:
            return VerifyError(
                reason=RefusalReason.STRIP_VERIFICATION_FAILED,
                detail="Reasoning patterns survived stripping — cannot proceed safely",
                retryable=False,
            )

        # Step 2: Route to alt-family
        try:
            route = self._router.select_verifier(request.caller.model_family)
        except RoutingError:
            return VerifyError(
                reason=RefusalReason.VERIFIER_UNAVAILABLE,
                detail="All cross-family routes have open circuit-breakers",
                retryable=True,
            )

        # Get provider for selected family
        provider = self._providers.get(route.family.value)
        if provider is None:
            return VerifyError(
                reason=RefusalReason.VERIFIER_UNAVAILABLE,
                detail=f"No provider configured for family={route.family.value}",
                retryable=False,
            )

        # Step 3: Resolve and execute lenses in parallel
        try:
            lenses = resolve_lenses(request.lenses)
        except ValueError as e:
            return VerifyError(
                reason=RefusalReason.VERIFIER_UNAVAILABLE,
                detail=str(e),
                retryable=False,
            )

        if len(lenses) < MIN_LENSES:
            return VerifyError(
                reason=RefusalReason.VERIFIER_UNAVAILABLE,
                detail=f"Lock 3 requires >= {MIN_LENSES} lenses, got {len(lenses)}",
                retryable=False,
            )

        # Create stripped artifact for lenses
        stripped_artifact = Artifact(
            type=request.artifact.type,
            content=strip_result.content,
            spec_hash=request.artifact.spec_hash,
        )

        # Fan-out: run all lenses in parallel
        selected_lenses = lenses[: request.budget.max_lenses]
        lens_tasks = [
            self._run_lens(lens, stripped_artifact, request.intent, route, provider)
            for lens in selected_lenses
        ]
        gathered = await asyncio.gather(*lens_tasks, return_exceptions=True)
        lens_results: list[LensResult] = []
        for lens, res in zip(selected_lenses, gathered, strict=True):
            if isinstance(res, BaseException):
                # Defense-in-depth: an unexpected error in one lens must never crash
                # the whole pipeline — record it as an errored UNCERTAIN placeholder.
                lens_results.append(
                    LensResult(
                        lens=lens.name,
                        model_family=route.family.value,
                        model_id=route.model_id,
                        outcome=LensOutcome.UNCERTAIN,
                        findings=[
                            Finding(
                                category="internal_error",
                                evidence=f"Lens raised an unexpected error: {res}",
                                severity="major",
                            )
                        ],
                        confidence=0.0,
                        errored=True,
                    )
                )
            else:
                lens_results.append(res)

        # Step 4: split genuine adjudications from provider/parse faults. Too few genuine
        # results means the verifier could not get enough independent signal -- that is an
        # availability fault (retryable), NOT a lens collapse and NOT a human escalation.
        genuine_results = [lr for lr in lens_results if not lr.errored]
        if len(genuine_results) < MIN_LENSES:
            return VerifyError(
                reason=RefusalReason.VERIFIER_UNAVAILABLE,
                detail=(
                    f"Only {len(genuine_results)} of {len(lens_results)} lenses produced a "
                    f"genuine result (need >= {MIN_LENSES}); the rest hit provider/parse faults"
                ),
                retryable=True,
            )

        # Step 5: Submodularity check over genuine results only -- fault placeholders share
        # identical finding keys and would otherwise trip a false LENS_COLLAPSE.
        sub_result = compute_pairwise_rho(
            genuine_results,
            thresholds=request.pairwise_rho_thresholds,
        )
        if not sub_result.passed:
            return VerifyError(
                reason=RefusalReason.LENS_COLLAPSE,
                detail=f"Lens pairs exceeded rho threshold: {sub_result.collapsed_pairs}",
                retryable=False,
            )

        # Step 6: aggregate verdict over genuine results.
        verdict, confidence, retryable = aggregate_verdict(genuine_results)

        # Generate revision hint if verdict is REVISE (from genuine findings only).
        revision_hint = None
        if verdict == Verdict.REVISE:
            hints = [
                f.evidence
                for lr in genuine_results
                for f in lr.findings
                if f.severity in ("critical", "major")
            ]
            if hints:
                revision_hint = "; ".join(hints)[:500]

        # Step 7: Generate receipt
        lens_results_json = json.dumps(
            [lr.model_dump() for lr in lens_results], default=str
        )

        lens_prompt_hashes = {
            lr.lens: lr.prompt_hash for lr in lens_results if lr.prompt_hash is not None
        }

        receipt = self._receipt_store.create_receipt(
            pre_strip_hash=strip_result.pre_strip_hash,
            post_strip_hash=strip_result.post_strip_hash,
            verifier_models=[route.model_id],
            pairwise_rho=sub_result.pairwise_rho,
            reasoning_visibility_mode=request.reasoning_visibility,
            verdict=verdict.value,
            confidence=confidence,
            retryable=retryable,
            lens_results_json=lens_results_json,
            lens_prompt_hashes=lens_prompt_hashes,
        )

        # Report success to router
        self._router.report_success(route.family, route.model_id)

        return VerifyResponse(
            verdict=verdict,
            confidence=confidence,
            retryable=retryable,
            revision_hint=revision_hint,
            lens_results=lens_results,
            pairwise_rho=sub_result.pairwise_rho,
            receipt=receipt,
        )

    async def _run_lens(
        self,
        lens: Lens,
        artifact: Artifact,
        intent: str,
        route: RouteSelection,
        provider: ModelProvider,
    ) -> LensResult:
        """Run a single lens, handling provider errors gracefully."""
        # Pin the exact prompts this lens issues (PIN_PER_STEP) so the receipt is
        # replayable even when the provider call fails.
        system_prompt, user_prompt = lens.build_prompts(artifact, intent)
        prompt_hash = compute_prompt_hash(system_prompt, user_prompt)
        try:
            result = await lens.evaluate(
                artifact=artifact,
                intent=intent,
                model_family=route.family.value,
                model_id=route.model_id,
                provider=provider,
            )
        except ProviderError as e:
            # Report failure to router for circuit-breaking
            self._router.report_failure(route.family, route.model_id)
            return LensResult(
                lens=lens.name,
                model_family=route.family.value,
                model_id=route.model_id,
                outcome=LensOutcome.UNCERTAIN,
                findings=[
                    Finding(
                        category="provider_error",
                        evidence=str(e),
                        severity="major",
                    )
                ],
                confidence=0.0,
                sees_reasoning=False,
                errored=True,
                prompt_hash=prompt_hash,
            )
        result.prompt_hash = prompt_hash
        return result
