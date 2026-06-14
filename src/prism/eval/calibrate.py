"""Calibration — turn measured runs into the design decisions Slice 1 exists to make.

Three pieces, all pure over ``EvalRun`` (so they unit-test deterministically):

- ``rho_threshold_sweep``: the roadmap's #1 gap. 0.25 is Rajan's *observed* correlation ceiling, not
  a validated refusal gate (design/07). This sweeps candidate cutoffs and asks, on prism's OWN data,
  "if we refused verifications whose max pairwise rho exceeds c, what accuracy/coverage do we get?"
  — so a future threshold change is data-driven, not asserted. (Kuncheva & Whitaker: rho alone is a
  weak predictor, so this is reported ALONGSIDE the submodular coverage-gain, never instead of it.)
- ``family_ab``: the same-vs-different-family experiment that DEMONSTRATES Lock 1 (Panickssery
  2024 self-preference). Positive delta = the lock helps. Meaningful only on real models.
- ``pairwise_prefer``: the CodeJudgeBench primitive — prism judges a (chosen, rejected) pair by
  verifying both and preferring the better verdict (CodeJudgeBench is pairwise > pointwise).
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass

from prism.eval.runner import EvalRun, RunRecord

_OFF_ACCEPT = {"refuse", "revise", "escalate"}
# Verdict desirability for pairwise preference (higher = prism judged the artifact better).
_VERDICT_RANK = {"accept": 3, "escalate": 2, "revise": 1, "refuse": 0}


def _by_sample(run: EvalRun) -> dict[str, list[RunRecord]]:
    grouped: dict[str, list[RunRecord]] = defaultdict(list)
    for r in run.records:
        grouped[r.sample_id].append(r)
    return grouped


def _sample_rows(run: EvalRun) -> list[tuple[float, bool]]:
    """Per sample: (max pairwise rho across runs, whether prism's modal verdict was correct).

    EVL-A-001 (sibling of report.summarize): records the engine could not adjudicate (a structural
    ``VerifyError`` -> ``unavailable=True``, stored with ``verdict=reason, confidence=0.0``) carry
    no real verdict and must NOT feed the modal-verdict / accuracy math here either — otherwise a
    transient provider outage during ``prism eval`` corrupts ``baseline_accuracy``, the per-cutoff
    accuracy, and the ``family_ab`` control. We mirror ``report.summarize`` exactly: ``unavailable``
    records are excluded; a sample with ZERO genuine records is SKIPPED (dropped, never scored as
    wrong); ``errored``-but-available records (a lens fault with a real verdict) are KEPT.
    """
    rows: list[tuple[float, bool]] = []
    for sid, recs in _by_sample(run).items():
        genuine = [r for r in recs if not r.unavailable]
        if not genuine:
            continue  # every run was verifier-unavailable: no measurement -> drop, don't score
        sample = run.samples[sid]
        modal = Counter(r.verdict for r in genuine).most_common(1)[0][0]
        correct = (modal in _OFF_ACCEPT) if sample.positive else (modal == "accept")
        rhos = [v for r in genuine for v in r.pairwise_rho.values()]
        rows.append((max(rhos) if rhos else 0.0, correct))
    return rows


@dataclass
class RhoSweep:
    points: list[tuple[float, float, float]]  # (cutoff, accuracy-on-kept, coverage)
    best_cutoff: float | None
    best_score: float  # accuracy * coverage at best_cutoff
    baseline_accuracy: float  # accuracy with no rho gating
    note: str


def rho_threshold_sweep(run: EvalRun, cutoffs: list[float] | None = None) -> RhoSweep:
    """Sweep the rho refusal cutoff; report the accuracy/coverage tradeoff on prism's data."""
    rows = _sample_rows(run)
    n = len(rows)
    if n == 0:
        return RhoSweep([], None, 0.0, 0.0, "no samples")
    baseline = sum(1 for _, c in rows if c) / n
    if cutoffs is None:
        cutoffs = [round(i / 100, 2) for i in range(0, 51, 5)]  # 0.00 .. 0.50 step 0.05
    points: list[tuple[float, float, float]] = []
    best_cutoff: float | None = None
    best_score = -1.0
    for c in cutoffs:
        kept = [(rho, corr) for rho, corr in rows if rho <= c]
        coverage = len(kept) / n
        accuracy = (sum(1 for _, corr in kept if corr) / len(kept)) if kept else 0.0
        score = accuracy * coverage  # balance correctness against how much we still cover
        points.append((c, accuracy, coverage))
        if score > best_score:
            best_score, best_cutoff = score, c
    distinct_rho = len({round(rho, 6) for rho, _ in rows})
    note = (
        "rho is ~constant across the corpus (offline mock, or no finding overlap on this set); the "
        "sweep is degenerate; calibrate on a REAL run with varied rho before changing 0.25."
        if distinct_rho <= 1
        else "Report beside the coverage-gain; do NOT change the runtime default on one corpus."
    )
    return RhoSweep(points, best_cutoff, best_score, baseline, note)


@dataclass
class FamilyAB:
    family_different_accuracy: float
    same_family_accuracy: float
    delta: float  # family_different - same_family; positive => the Lock-1 family split helps
    note: str


def _accuracy(run: EvalRun) -> float:
    rows = _sample_rows(run)
    return (sum(1 for _, c in rows if c) / len(rows)) if rows else 0.0


def family_ab(family_different: EvalRun, same_family: EvalRun) -> FamilyAB:
    """Accuracy delta between prism's family-different verifier and a same-family control."""
    fd = _accuracy(family_different)
    sf = _accuracy(same_family)
    note = (
        "Positive delta = the family-different lock helps (a same-family verifier self-prefers and "
        "misses defects, per Panickssery 2024). Meaningful only with REAL models; offline mocks do "
        "not self-prefer, so the offline delta is ~0 and not evidence either way."
    )
    return FamilyAB(fd, sf, fd - sf, note)


def pairwise_prefer(
    verdict_a: str, confidence_a: float, verdict_b: str, confidence_b: float
) -> str:
    """CodeJudgeBench primitive: which artifact does prism judge better? Returns 'a' | 'b' | 'tie'.

    Rank by verdict desirability (accept > escalate > revise > refuse), tie-break by confidence.
    CodeJudgeBench is pairwise (chosen vs rejected); prism is correct when it prefers 'chosen'.
    """
    rank_a = _VERDICT_RANK.get(verdict_a, -1)
    rank_b = _VERDICT_RANK.get(verdict_b, -1)
    if rank_a != rank_b:
        return "a" if rank_a > rank_b else "b"
    if abs(confidence_a - confidence_b) < 1e-9:
        return "tie"
    return "a" if confidence_a > confidence_b else "b"
