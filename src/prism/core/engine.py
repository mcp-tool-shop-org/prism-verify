"""Core verification engine.

Orchestrates: strip -> route -> fan-out lenses -> rho check -> aggregate -> receipt.
This is the main verify() entrypoint that everything else wraps (CLI, MCP, HTTP).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from typing import Literal

from pydantic import ValidationError

from prism.core.citations import (
    build_citation_groundedness_prompts,
    numeric_mismatch,
    numeric_unit_mismatch,
    parse_citation_groundedness,
    parse_citations,
)
from prism.core.routing import FamilyRouter, RouteSelection, RoutingError
from prism.core.stripping import StripVerificationError, strip_reasoning
from prism.core.submodularity import compute_pairwise_rho
from prism.core.types import (
    Artifact,
    ArtifactType,
    Citation,
    CitationResult,
    ExistenceOutcome,
    Finding,
    FindingMatch,
    LensOutcome,
    LensResult,
    RefusalReason,
    Verdict,
    VerifyError,
    VerifyRequest,
    VerifyResponse,
)
from prism.lenses.base import Lens, compute_prompt_hash
from prism.lenses.nli import nli_floor_enabled, nli_groundedness
from prism.lenses.registry import resolve_lenses
from prism.providers.base import CompletionRequest, ModelProvider, ProviderError
from prism.receipts.store import ReceiptStore
from prism.retrieval.oracle import CitationOracle, ExistenceResult

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


def _citation_as_lensresult(cr: CitationResult) -> LensResult:
    """Project a per-citation verdict onto a LensResult so aggregate_verdict can fold it.

    Citations have no LLM-lens ensemble to average; this lets the artifact-level verdict reuse
    the same conservative ordering (any REFUSE -> REFUSE; else any REVISE -> REVISE; else any
    ESCALATE -> ESCALATE; else ACCEPT).
    """
    severity: Literal["critical", "major", "minor"]
    if cr.verdict == Verdict.REFUSE:
        outcome, severity = LensOutcome.FAIL, "critical"
    elif cr.verdict == Verdict.REVISE:
        outcome, severity = LensOutcome.FAIL, "major"
    elif cr.verdict == Verdict.ESCALATE:
        outcome, severity = LensOutcome.UNCERTAIN, "major"
    else:
        outcome, severity = LensOutcome.PASS, "minor"
    findings = (
        []
        if outcome == LensOutcome.PASS
        else [Finding(category="citation", evidence=cr.detail, severity=severity)]
    )
    return LensResult(
        lens="citation",
        model_family="oracle",
        model_id="retrieval",
        outcome=outcome,
        findings=findings,
        # Carry the groundedness lens's parsed confidence when the verdict came from that
        # probabilistic stage; deterministic existence outcomes leave it unset -> 1.0 (CORE-A-003).
        confidence=cr.confidence if cr.confidence is not None else 1.0,
    )


class VerificationEngine:
    """Core engine that executes the full verification pipeline."""

    def __init__(
        self,
        providers: dict[str, ModelProvider],
        router: FamilyRouter | None = None,
        receipt_store: ReceiptStore | None = None,
        oracle: CitationOracle | None = None,
    ) -> None:
        self._providers = providers
        self._router = router or FamilyRouter()
        self._receipt_store = receipt_store or ReceiptStore()
        self._oracle = oracle or CitationOracle()

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
        # v0.3: citations take a distinct path (deterministic existence floor -> numeric
        # guard -> RAG-fed groundedness lens), not the code-artifact multi-lens pipeline.
        if request.artifact.type == ArtifactType.CITATIONS:
            return await self._verify_citations(request)

        # Step 1: Strip reasoning
        try:
            strip_result = strip_reasoning(request.artifact.content)
        except StripVerificationError:
            return VerifyError(
                reason=RefusalReason.STRIP_VERIFICATION_FAILED,
                detail="Reasoning patterns survived stripping — cannot proceed safely",
                retryable=False,
            )

        # Step 2: Route to alt-family. Pass the set of configured provider families so the
        # router walks past candidates we cannot actually serve instead of dead-ending on a
        # family with no provider (the local-only-deployment trap).
        try:
            route = self._router.select_verifier(
                request.caller.model_family,
                available_families=set(self._providers.keys()),
            )
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
        # The latency budget is a hard ANDON ceiling: if the lens fan-out cannot finish
        # within the caller's declared max_latency_ms, refuse with BUDGET_EXCEEDED rather
        # than block the caller's agent step past its budget.
        try:
            gathered = await asyncio.wait_for(
                asyncio.gather(*lens_tasks, return_exceptions=True),
                timeout=request.budget.max_latency_ms / 1000,
            )
        except TimeoutError:
            return VerifyError(
                reason=RefusalReason.BUDGET_EXCEEDED,
                detail=(
                    f"Lens fan-out exceeded the {request.budget.max_latency_ms}ms "
                    "latency budget"
                ),
                retryable=True,
            )
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

    async def _verify_citations(
        self, request: VerifyRequest
    ) -> VerifyResponse | VerifyError:
        """Citation path: existence floor -> numeric guard -> groundedness, per citation.

        The four code-artifact locks are reinterpreted here as three mechanism-diverse stages
        (a retrieval oracle, a numeric parser, a family-different LLM lens), which are
        decorrelated by construction — so MIN_LENSES / submodularity (designed for same-
        mechanism LLM lenses) do not apply. See design/04-citation-verification.md.
        """
        try:
            citations = parse_citations(request.artifact.content)
        except (json.JSONDecodeError, ValueError, ValidationError) as exc:
            return VerifyError(
                reason=RefusalReason.INVALID_ARTIFACT,
                detail=f"citations artifact is not a valid JSON array of citations: {exc}",
                retryable=False,
            )
        if not citations:
            return VerifyError(
                reason=RefusalReason.INVALID_ARTIFACT,
                detail="citations artifact contained no citations",
                retryable=False,
            )

        # Route to a family-different verifier for the groundedness stage.
        try:
            route = self._router.select_verifier(
                request.caller.model_family,
                available_families=set(self._providers.keys()),
            )
        except RoutingError:
            return VerifyError(
                reason=RefusalReason.VERIFIER_UNAVAILABLE,
                detail="All cross-family routes have open circuit-breakers",
                retryable=True,
            )
        provider = self._providers.get(route.family.value)
        if provider is None:
            return VerifyError(
                reason=RefusalReason.VERIFIER_UNAVAILABLE,
                detail=f"No provider configured for family={route.family.value}",
                retryable=False,
            )

        results: list[CitationResult] = []
        lens_results: list[LensResult] = []
        pins: list[dict[str, str]] = []
        for i, citation in enumerate(citations):
            existence = await self._oracle.resolve(citation)
            pins.append(
                {
                    "id": citation.id or "",
                    "identifier": citation.identifier or "",
                    "query": existence.query,
                    "source_sha256": existence.source_sha256 or "",
                    "existence": existence.outcome.value,
                }
            )
            cr, lr = await self._adjudicate_citation(
                i, citation, existence, route, provider
            )
            results.append(cr)
            if lr is not None:
                lens_results.append(lr)

        pseudo = [_citation_as_lensresult(cr) for cr in results]
        verdict, confidence, retryable = aggregate_verdict(pseudo)

        hints = [
            f"{cr.action}: {cr.detail}" for cr in results if cr.verdict == Verdict.REVISE
        ]
        revision_hint = "; ".join(hints)[:500] if hints else None

        content_hash = hashlib.sha256(request.artifact.content.encode()).hexdigest()
        lens_results_json = json.dumps([lr.model_dump() for lr in lens_results], default=str)
        lens_prompt_hashes = {
            lr.lens: lr.prompt_hash for lr in lens_results if lr.prompt_hash is not None
        }
        receipt = self._receipt_store.create_receipt(
            pre_strip_hash=content_hash,
            post_strip_hash=content_hash,
            verifier_models=[route.model_id],
            pairwise_rho={},
            reasoning_visibility_mode=request.reasoning_visibility,
            verdict=verdict.value,
            confidence=confidence,
            retryable=retryable,
            lens_results_json=lens_results_json,
            lens_prompt_hashes=lens_prompt_hashes,
            artifact_type=request.artifact.type.value,
            retrieval_pins=pins,
        )
        self._router.report_success(route.family, route.model_id)
        return VerifyResponse(
            verdict=verdict,
            confidence=confidence,
            retryable=retryable,
            revision_hint=revision_hint,
            lens_results=lens_results,
            pairwise_rho={},
            citation_results=results,
            receipt=receipt,
        )

    async def _adjudicate_citation(
        self,
        index: int,
        citation: Citation,
        existence: ExistenceResult,
        route: RouteSelection,
        provider: ModelProvider,
    ) -> tuple[CitationResult, LensResult | None]:
        """Map a citation's existence/numeric/groundedness outcome to a verdict + action.

        ``index`` is the citation's position in the artifact; it makes the groundedness
        lens name unique even when two citations share an id/identifier, so the receipt's
        lens_prompt_hashes never collide and drop a pin (CORE-A-002).
        """
        cid, ident = citation.id, citation.identifier

        if existence.outcome == ExistenceOutcome.FABRICATED:
            return (
                CitationResult(
                    citation_id=cid,
                    identifier=ident,
                    existence=existence.outcome,
                    verdict=Verdict.REFUSE,
                    action="DROP",
                    detail=existence.detail,
                ),
                None,
            )
        if existence.outcome == ExistenceOutcome.METADATA_MISMATCH:
            return (
                CitationResult(
                    citation_id=cid,
                    identifier=ident,
                    existence=existence.outcome,
                    verdict=Verdict.REVISE,
                    action="FIX METADATA",
                    detail=existence.detail,
                    source_title=existence.source_title,
                ),
                None,
            )
        if existence.outcome == ExistenceOutcome.UNRESOLVABLE:
            return (
                CitationResult(
                    citation_id=cid,
                    identifier=ident,
                    existence=existence.outcome,
                    verdict=Verdict.ESCALATE,
                    action="RETRIEVE MANUALLY",
                    detail=existence.detail,
                ),
                None,
            )

        # RESOLVED -> numeric guard (deterministic), then groundedness (LLM lens).
        source_text = f"{existence.source_title or ''}\n\n{existence.source_abstract or ''}"
        mismatched, mism_detail = numeric_mismatch(citation.claim, source_text)
        if mismatched:
            return (
                CitationResult(
                    citation_id=cid,
                    identifier=ident,
                    existence=ExistenceOutcome.RESOLVED,
                    finding_match=FindingMatch.CONTRADICTED,
                    verdict=Verdict.REVISE,
                    action="FIX TO MATCH SOURCE",
                    detail=mism_detail,
                    source_title=existence.source_title,
                    source_abstract=existence.source_abstract,
                ),
                None,
            )
        unit_bad, unit_detail = numeric_unit_mismatch(citation.claim, source_text)
        if unit_bad:
            return (
                CitationResult(
                    citation_id=cid,
                    identifier=ident,
                    existence=ExistenceOutcome.RESOLVED,
                    finding_match=FindingMatch.CONTRADICTED,
                    verdict=Verdict.REVISE,
                    action="FIX TO MATCH SOURCE",
                    detail=unit_detail,
                    source_title=existence.source_title,
                    source_abstract=existence.source_abstract,
                ),
                None,
            )
        if not (existence.source_abstract and existence.source_abstract.strip()):
            return (
                CitationResult(
                    citation_id=cid,
                    identifier=ident,
                    existence=ExistenceOutcome.RESOLVED,
                    finding_match=FindingMatch.NOT_ADDRESSED,
                    verdict=Verdict.ESCALATE,
                    action="RETRIEVE FULL TEXT",
                    detail="resolved, but no abstract was available to ground the claim",
                    source_title=existence.source_title,
                ),
                None,
            )

        system, user = build_citation_groundedness_prompts(
            citation.claim, existence.source_title or "", existence.source_abstract
        )
        prompt_hash = compute_prompt_hash(system, user)
        lens_name = f"citation_groundedness:{index}:{cid or ident or '?'}"
        try:
            resp = await provider.complete(
                CompletionRequest(
                    system_prompt=system, user_prompt=user, model_id=route.model_id
                )
            )
        except ProviderError as exc:
            self._router.report_failure(route.family, route.model_id)
            lr = LensResult(
                lens=lens_name,
                model_family=route.family.value,
                model_id=route.model_id,
                outcome=LensOutcome.UNCERTAIN,
                findings=[
                    Finding(category="provider_error", evidence=str(exc), severity="major")
                ],
                confidence=0.0,
                errored=True,
                prompt_hash=prompt_hash,
            )
            return (
                CitationResult(
                    citation_id=cid,
                    identifier=ident,
                    existence=ExistenceOutcome.RESOLVED,
                    finding_match=FindingMatch.NOT_ADDRESSED,
                    verdict=Verdict.ESCALATE,
                    action="RETRIEVE MANUALLY",
                    detail=f"groundedness verifier unavailable: {exc}",
                    source_title=existence.source_title,
                    source_abstract=existence.source_abstract,
                ),
                lr,
            )

        gnd, span, conf = parse_citation_groundedness(resp.content)
        if gnd == "supported":
            fmatch, verdict, action = FindingMatch.SUPPORTED, Verdict.ACCEPT, "OK"
            detail, lens_outcome = "source supports the claim", LensOutcome.PASS
        elif gnd == "contradicted":
            fmatch, verdict, action = (
                FindingMatch.CONTRADICTED,
                Verdict.REVISE,
                "FIX TO MATCH SOURCE",
            )
            detail, lens_outcome = "retrieved source contradicts the claim", LensOutcome.FAIL
        else:
            fmatch, verdict, action = (
                FindingMatch.NOT_ADDRESSED,
                Verdict.ESCALATE,
                "RETRIEVE FULL TEXT",
            )
            detail = "claim is not addressed in the title+abstract"
            lens_outcome = LensOutcome.UNCERTAIN
        # Orthogonal NLI floor (opt-in, PRISM_NLI_FLOOR): a mechanistically-different encoder-NLI
        # check vetoes a "supported" the LLM lens gave but a different mechanism does not
        # corroborate (wave-10). Abstains (no-op) when the optional `nli` extra is absent.
        nli_findings: list[Finding] = []
        if verdict == Verdict.ACCEPT and nli_floor_enabled():
            nli_verdict = nli_groundedness(citation.claim, source_text)
            if nli_verdict is not None and nli_verdict != "supported":
                fmatch = FindingMatch.NOT_ADDRESSED
                verdict = Verdict.ESCALATE
                action = "VERIFY: ORTHOGONAL NLI DISAGREES"
                detail = (
                    "the LLM lens found the claim supported, but a mechanistically-orthogonal "
                    f"NLI check returned '{nli_verdict}'"
                )
                lens_outcome = LensOutcome.UNCERTAIN
                nli_findings = [
                    Finding(
                        category="nli_floor",
                        evidence=f"orthogonal NLI verdict: {nli_verdict}",
                        severity="major",
                    )
                ]
        lr = LensResult(
            lens=lens_name,
            model_family=route.family.value,
            model_id=route.model_id,
            outcome=lens_outcome,
            findings=nli_findings,
            confidence=conf,
            prompt_hash=prompt_hash,
        )
        return (
            CitationResult(
                citation_id=cid,
                identifier=ident,
                existence=ExistenceOutcome.RESOLVED,
                finding_match=fmatch,
                verdict=verdict,
                action=action,
                detail=detail,
                source_title=existence.source_title,
                source_abstract=existence.source_abstract,
                supporting_span=span,
                confidence=conf,
            ),
            lr,
        )
