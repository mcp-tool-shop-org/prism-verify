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
from dataclasses import dataclass

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


@dataclass(frozen=True)
class EvalRun:
    """The full set of raw records plus the samples and run metadata."""

    records: list[RunRecord]
    samples: dict[str, Sample]
    n_runs: int
    verifier_label: str
    caller_family: str


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
) -> EvalRun:
    """Run every sample through ``engine.verify`` ``n_runs`` times and collect raw records."""
    if n_runs < 1:
        raise ValueError("n_runs must be >= 1")
    family = ModelFamily(caller_family)
    records: list[RunRecord] = []
    for sample in samples:
        request = VerifyRequest(
            artifact=Artifact(type=ArtifactType(sample.artifact_type), content=sample.content),
            intent=sample.intent,
            caller=CallerContext(model_family=family, model_id=caller_model),
            budget=Budget(max_latency_ms=max_latency_ms),
        )
        for run_index in range(n_runs):
            result = await engine.verify(request)
            records.append(_to_record(sample, run_index, result))
    return EvalRun(
        records=records,
        samples={s.id: s for s in samples},
        n_runs=n_runs,
        verifier_label=verifier_label,
        caller_family=caller_family,
    )
