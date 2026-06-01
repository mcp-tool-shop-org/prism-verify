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
from prism.lenses.base import Lens
from prism.lenses.registry import resolve_lenses
from prism.providers.base import ModelProvider, ProviderError
from prism.receipts.store import ReceiptStore

# Minimum lenses required (Lock 3)
MIN_LENSES = 3


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
        4. RHO check (submodularity)
        5. AGGREGATE verdict
        6. RECEIPT generation
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

        # Step 4: Submodularity check
        sub_result = compute_pairwise_rho(
            lens_results,
            thresholds=request.pairwise_rho_thresholds,
        )

        if not sub_result.passed:
            return VerifyError(
                reason=RefusalReason.LENS_COLLAPSE,
                detail=f"Lens pairs exceeded rho threshold: {sub_result.collapsed_pairs}",
                retryable=False,
            )

        # Step 5: Aggregate verdict
        verdict, confidence, retryable = self._aggregate_verdict(lens_results)

        # Generate revision hint if verdict is REVISE
        revision_hint = None
        if verdict == Verdict.REVISE:
            # Collect critical/major findings as hint
            hints = []
            for lr in lens_results:
                for f in lr.findings:
                    if f.severity in ("critical", "major"):
                        hints.append(f.evidence)
            if hints:
                revision_hint = "; ".join(hints)[:500]

        # Step 6: Generate receipt
        lens_results_json = json.dumps(
            [lr.model_dump() for lr in lens_results], default=str
        )

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
        try:
            return await lens.evaluate(
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
            )

    def _aggregate_verdict(
        self, lens_results: list[LensResult]
    ) -> tuple[Verdict, float, bool]:
        """Aggregate lens results into a single verdict.

        Logic:
        - Any lens FAIL with critical finding -> REFUSE
        - Any lens FAIL with major finding -> REVISE
        - All lenses UNCERTAIN -> ESCALATE
        - All lenses PASS -> ACCEPT
        - Mixed -> lowest severity drives verdict
        """

        has_critical = False
        has_major_fail = False
        all_uncertain = True
        all_pass = True
        confidences = []

        for lr in lens_results:
            confidences.append(lr.confidence)

            if lr.outcome == LensOutcome.PASS:
                all_uncertain = False
            elif lr.outcome == LensOutcome.FAIL:
                all_uncertain = False
                all_pass = False
                for f in lr.findings:
                    if f.severity == "critical":
                        has_critical = True
                    elif f.severity == "major":
                        has_major_fail = True
            elif lr.outcome == LensOutcome.UNCERTAIN:
                all_pass = False

        # Compute confidence as minimum (conservative)
        confidence = min(confidences) if confidences else 0.0

        if has_critical:
            return Verdict.REFUSE, confidence, False
        elif has_major_fail:
            return Verdict.REVISE, confidence, True
        elif all_uncertain:
            return Verdict.ESCALATE, confidence, False
        elif all_pass:
            return Verdict.ACCEPT, confidence, False
        else:
            # Mixed uncertain + pass
            return Verdict.ACCEPT, confidence, False
