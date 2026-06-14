"""Benchmark runner — run prism's engine over the labeled corpus and capture raw records.

Each (sample, run) yields a ``RunRecord``: the artifact verdict, per-lens PASS/FAIL/UNCERTAIN
outcomes, the pairwise-rho matrix, and the confidence. ``report.py`` turns these into the measured
metrics. N>=3 runs at a pinned temperature is the single-artifact variance control (position/order
bias is a pairwise-judging concern, not prism's single-artifact path — see design/07).

A ``MockProvider`` powers ``--offline``: a DETERMINISTIC verifier for smoke/CI. Its numbers are
NOT a real measurement — only a real provider (Ollama or a hosted family) yields meaningful P/R.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from prism.core.engine import VerificationEngine
from prism.core.types import (
    Artifact,
    ArtifactType,
    Budget,
    CallerContext,
    ModelFamily,
    VerifyError,
    VerifyRequest,
    VerifyResponse,
)
from prism.eval.corpus import Sample
from prism.providers.base import (
    CompletionRequest,
    CompletionResponse,
    ModelProvider,
)

# Distinctive substring of each lens's SYSTEM_PROMPT -> lens name (so the mock can identify it).
_LENS_MARKERS: tuple[tuple[str, str], ...] = (
    ("contract-completeness verifier", "contract_completeness"),
    ("cross-boundary information flow verifier", "cross_boundary"),
    ("invariant and test-adequacy verifier", "invariant"),
    ("groundedness verifier", "groundedness"),
)

# (lens_name, artifact_text) -> (outcome, confidence). outcome in {"pass","fail","uncertain"}.
DecidePolicy = Callable[[str, str], tuple[str, float]]


@dataclass(frozen=True)
class RunRecord:
    """One (sample, run) result, flattened for metric computation."""

    sample_id: str
    run_index: int
    verdict: str  # Verdict value, or a RefusalReason value if the engine returned VerifyError
    confidence: float
    errored: bool  # any lens hit a provider/parse fault, OR the engine returned VerifyError
    unavailable: bool  # the engine returned a structural VerifyError (no verdict)
    per_lens: dict[str, str]  # lens name -> outcome value ("pass"|"fail"|"uncertain")
    pairwise_rho: dict[str, float]
    # EVS-B-001: the RESOLVED verifier model id(s) the engine actually used for this adjudication
    # (from each LensResult.model_id). Empty on an unavailable record (no lens produced a verdict).
    model_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class EvalRun:
    """The full set of raw records plus the samples and run metadata."""

    records: list[RunRecord]
    samples: dict[str, Sample]
    n_runs: int
    verifier_label: str
    caller_family: str
    # EVS-B-001/002 reproducibility provenance — recorded HONESTLY so a published report names which
    # model(s) produced the numbers, at what temperature/seed, over which corpus content-hash.
    resolved_model_ids: list[str] = field(default_factory=list)  # distinct, sorted
    effective_temperature: float | None = None  # the temperature actually sent to the verifier
    seed: int | None = None  # provider seed if one was sent; None = not seeded (recorded honestly)
    corpus_content_hash: str | None = None  # corpus.corpus_content_hash of the scored sample set


def _lens_from_system(system_prompt: str) -> str:
    for marker, lens in _LENS_MARKERS:
        if marker in system_prompt:
            return lens
    return "unknown"


def _artifact_from_user(user_prompt: str) -> str:
    """Pull the artifact body out of a lens user-prompt (between the first ``` fences)."""
    m = re.search(r"```\n?(.*?)\n?```", user_prompt, re.DOTALL)
    return m.group(1) if m else user_prompt


def default_offline_policy(lens: str, artifact: str) -> tuple[str, float]:
    """Deterministic, content-varying mock verdict — exercises metric paths; NOT a real signal."""
    h = int(hashlib.sha256(f"{lens}\x00{artifact}".encode()).hexdigest(), 16)
    outcome = "fail" if h % 2 == 0 else "pass"
    confidence = 0.5 + (h % 50) / 100.0  # 0.50..0.99, deterministic
    return outcome, confidence


def same_family_self_preferring_policy(lens: str, artifact: str) -> tuple[str, float]:
    """Deterministic OFFLINE control policy: a same-family judge that OVER-ACCEPTS (self-prefers).

    Models the empirical self-preference failure (Panickssery 2024): a same-family verifier is too
    forgiving of the producer's output and MISSES defects. Here it ALWAYS returns PASS, so the
    control engine never flags anything and accepts every artifact — wrong on every positive
    (defect-bearing) sample, while the family-different treatment (``default_offline_policy``) still
    catches a content-varying share of them. Over the paired corpus this yields a DETERMINISTIC,
    SIGNED-POSITIVE delta (treatment > control), proving the --family-ab wiring end-to-end at zero
    cost. It is MACHINERY, not evidence: it is a fixed mock, not a measurement of any real model's
    self-preference (the report says so). Used only by ``_build_same_family_control``'s offline arm.
    """
    # Confidence is deterministic + content-varying so calibration paths still exercise (and so the
    # over-accepts are confidently wrong, the realistic self-preference shape).
    h = int(hashlib.sha256(f"selfpref\x00{lens}\x00{artifact}".encode()).hexdigest(), 16)
    confidence = 0.5 + (h % 50) / 100.0  # 0.50..0.99, deterministic
    return "pass", confidence


class MockProvider(ModelProvider):
    """Deterministic mock verifier for offline runs/tests. On FAIL it returns lens-distinct
    findings, so the submodularity check never spuriously collapses (distinct finding category)."""

    def __init__(
        self,
        decide: DecidePolicy = default_offline_policy,
        *,
        family: ModelFamily = ModelFamily.LOCAL,
        model_id: str = "offline-mock",
    ) -> None:
        self._decide = decide
        self._family = family
        self._model = model_id

    @property
    def family(self) -> ModelFamily:
        return self._family

    @property
    def available_models(self) -> list[str]:
        return [self._model]

    async def complete(self, request: CompletionRequest) -> CompletionResponse:
        lens = _lens_from_system(request.system_prompt)
        artifact = _artifact_from_user(request.user_prompt)
        outcome, confidence = self._decide(lens, artifact)
        findings = (
            [{"category": f"{lens}_finding", "line": 1, "evidence": "mock", "severity": "major"}]
            if outcome == "fail"
            else []
        )
        body = {"outcome": outcome, "confidence": confidence, "findings": findings}
        return CompletionResponse(content=json.dumps(body), model_id=self._model, latency_ms=1)

    async def health_check(self) -> bool:
        return True


def _to_record(sample: Sample, run_index: int, result: VerifyResponse | VerifyError) -> RunRecord:
    if isinstance(result, VerifyError):
        return RunRecord(
            sample_id=sample.id,
            run_index=run_index,
            verdict=result.reason.value,
            confidence=0.0,
            errored=True,
            unavailable=True,
            per_lens={},
            pairwise_rho={},
        )
    return RunRecord(
        sample_id=sample.id,
        run_index=run_index,
        verdict=result.verdict.value,
        confidence=result.confidence,
        errored=any(lr.errored for lr in result.lens_results),
        unavailable=False,
        per_lens={lr.lens: lr.outcome.value for lr in result.lens_results},
        pairwise_rho=dict(result.pairwise_rho),
        # EVS-B-001: capture the resolved verifier model id of every lens that produced a result, so
        # the report can name WHICH model produced the numbers. Sorted+deduped for stable output.
        model_ids=tuple(sorted({lr.model_id for lr in result.lens_results if lr.model_id})),
    )


async def run_eval(
    engine: VerificationEngine,
    samples: Sequence[Sample],
    *,
    caller_family: str = "anthropic",
    caller_model: str = "corpus-caller",
    n_runs: int = 3,
    max_latency_ms: int = 30000,
    verifier_label: str = "",
    corpus_content_hash: str | None = None,
    seed: int | None = None,
) -> EvalRun:
    """Run every sample through ``engine.verify`` ``n_runs`` times and collect raw records.

    EVS-B-001/002 reproducibility: the run records the RESOLVED verifier model id(s) actually used
    (collected from each adjudication's lens results), the effective temperature, an optional seed,
    and the corpus content-hash — so the emitted report is reproducible-by-construction, not just
    asserted. The engine builds its ``CompletionRequest`` without overriding temperature, so the
    effective verifier temperature is ``CompletionRequest``'s default; we read it from there rather
    than hardcoding a number we might drift from. ``seed`` is recorded HONESTLY: the current
    provider path does not thread a seed, so it stays ``None`` unless a caller passes one (don't
    fake determinism we can't deliver — record what was actually used).
    """
    if n_runs < 1:
        raise ValueError("n_runs must be >= 1")
    family = ModelFamily(caller_family)
    # The engine builds its CompletionRequest without overriding temperature, so the effective
    # verifier temperature IS the dataclass default. Read it from a default instance (honest, and
    # tracks the source-of-truth) rather than hardcoding a literal we might drift from.
    effective_temperature = CompletionRequest(
        system_prompt="", user_prompt="", model_id=""
    ).temperature
    records: list[RunRecord] = []
    resolved: set[str] = set()
    for sample in samples:
        request = VerifyRequest(
            artifact=Artifact(type=ArtifactType(sample.artifact_type), content=sample.content),
            intent=sample.intent,
            caller=CallerContext(model_family=family, model_id=caller_model),
            budget=Budget(max_latency_ms=max_latency_ms),
        )
        for run_index in range(n_runs):
            result = await engine.verify(request)
            record = _to_record(sample, run_index, result)
            resolved.update(record.model_ids)
            records.append(record)
    return EvalRun(
        records=records,
        samples={s.id: s for s in samples},
        n_runs=n_runs,
        verifier_label=verifier_label,
        caller_family=caller_family,
        resolved_model_ids=sorted(resolved),
        effective_temperature=effective_temperature,
        seed=seed,
        corpus_content_hash=corpus_content_hash,
    )
