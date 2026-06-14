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

import math
from collections import Counter, defaultdict
from dataclasses import dataclass, field

from prism.core.routing import DEFAULT_ROUTING_MAP
from prism.core.types import ModelFamily
from prism.eval.runner import EvalRun, RunRecord
from prism.providers.base import ModelProvider

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


# ── Family auto-discovery for the --family-ab control arm (F-01 1B) ────────────────────────────


def discover_families(providers: dict[str, ModelProvider]) -> set[ModelFamily]:
    """The set of model families that have a configured provider (from ``ModelProvider.family``)."""
    return {p.family for p in providers.values()}


@dataclass
class AbPair:
    """Result of ``pick_ab_pair``: the two arms to run, or a reason the A/B cannot run.

    When ``treatment`` and ``control`` are both set, the caller runs the treatment
    (family-different) arm against the same-family control. When ``reason`` is set (and the families
    are None), the family-AB is SKIPPED with that reason printed — never silently scored as 0.0.
    """

    treatment: ModelFamily | None
    control: ModelFamily | None
    reason: str | None = None

    @property
    def ok(self) -> bool:
        return self.treatment is not None and self.control is not None


def pick_ab_pair(caller_family: ModelFamily, available: set[ModelFamily]) -> AbPair:
    """Pick the (treatment_family, control_family) for the Lock-1 A/B, or a SKIP reason.

    - control_family is always the caller's own family (the same-family control arm). If the caller
      family has no configured provider there is no control to run -> skip.
    - treatment_family is the FIRST cross-family verifier in ``DEFAULT_ROUTING_MAP[caller_family]``
      that is ALSO in ``available`` (i.e. configured). If no cross-family verifier is configured
      there is no treatment arm -> skip.

    Returns an ``AbPair`` with both families when both arms are runnable, else with ``reason`` set
    and the families None (so the CLI prints the reason rather than emitting a meaningless delta).
    """
    if caller_family not in available:
        return AbPair(
            None,
            None,
            reason=(
                f"no provider configured for the caller family '{caller_family.value}' — the "
                "same-family control arm cannot run (set its API key / endpoint)."
            ),
        )
    for alt_family, _model_id in DEFAULT_ROUTING_MAP.get(caller_family, []):
        if alt_family != caller_family and alt_family in available:
            return AbPair(treatment=alt_family, control=caller_family)
    return AbPair(
        None,
        None,
        reason=(
            f"no cross-family verifier is configured for caller '{caller_family.value}' — the "
            "family-different treatment arm cannot run (configure a different-family provider)."
        ),
    )


@dataclass
class FamilyAB:
    family_different_accuracy: float
    same_family_accuracy: float
    delta: float  # family_different - same_family; positive => the Lock-1 family split helps
    note: str
    # F-01 1C: paired (McNemar) statistics over the INTERSECTION of samples both arms measured.
    n_paired: int = 0
    family_different_correct: int = 0
    same_family_correct: int = 0
    delta_ci: tuple[float, float] = (0.0, 0.0)
    # F-01 1F: the resolved verifier model id(s) each arm actually used, so the report names WHICH
    # models produced the delta (honest provenance for both arms, not just the treatment).
    family_different_model_ids: list[str] = field(default_factory=list)
    same_family_model_ids: list[str] = field(default_factory=list)


def _correct_by_sample(run: EvalRun) -> dict[str, bool]:
    """Per sample_id: whether prism's modal verdict was correct, over GENUINE records only.

    Reuses the EVL-A-001 unavailable-exclusion rule (same as ``_sample_rows``): ``unavailable``
    records carry no real verdict and are dropped; a sample whose every record is unavailable is
    OMITTED from the dict entirely (no key) — never scored. The key set of this dict is exactly the
    samples the arm actually measured, which is what the paired (McNemar) intersection is built on.
    """
    out: dict[str, bool] = {}
    for sid, recs in _by_sample(run).items():
        genuine = [r for r in recs if not r.unavailable]
        if not genuine:
            continue  # no measurement for this sample in this arm
        sample = run.samples[sid]
        modal = Counter(r.verdict for r in genuine).most_common(1)[0][0]
        out[sid] = (modal in _OFF_ACCEPT) if sample.positive else (modal == "accept")
    return out


def _mcnemar_delta_ci(b: int, c: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wald CI on the difference of two correlated proportions (paired/McNemar form).

    For n paired observations, let b = #(treatment correct, control wrong) and
    c = #(treatment wrong, control correct) be the DISCORDANT pairs. The paired accuracy difference
    is delta = (b - c) / n. Its variance (the standard McNemar/correlated-proportions Wald variance)
    is Var = [ (b + c) - (b - c)^2 / n ] / n^2, so SE = sqrt(Var). The 95% CI is delta +/- z*SE,
    clamped to [-1, 1]. Pure Python, no numpy/scipy. (Concordant pairs contribute 0 to the
    difference and only enter through n; with no discordant pairs the interval collapses to [0, 0].)
    """
    if n == 0:
        return (0.0, 0.0)
    delta = (b - c) / n
    var = ((b + c) - (b - c) ** 2 / n) / (n * n)
    se = math.sqrt(var) if var > 0 else 0.0
    lo = max(-1.0, delta - z * se)
    hi = min(1.0, delta + z * se)
    return (lo, hi)


def compute_family_ab(treatment_run: EvalRun, control_run: EvalRun) -> FamilyAB:
    """Paired (McNemar) accuracy delta between the family-different arm and the same-family control.

    Pairs by ``sample_id`` over the INTERSECTION of samples where BOTH arms produced >=1 genuine
    record (so a sample only one arm could measure is excluded — you cannot pair what you did not
    measure on both sides). ``n_paired`` is the size of that intersection. Over the paired set:

    - ``family_different_accuracy`` / ``same_family_accuracy`` are each arm's accuracy ON THE PAIRED
      SET (not the per-arm full set), so they are directly comparable.
    - ``delta`` = family_different_accuracy - same_family_accuracy = (b - c) / n_paired.
    - ``delta_ci`` is the McNemar Wald CI on that paired difference (``_mcnemar_delta_ci``).

    A positive delta means the family-different lock helps (the same-family control self-prefers and
    misses defects, per Panickssery 2024). ``n_paired == 0`` is a genuine failure mode (e.g. the
    control arm produced no verdict — Lock-1 bypass failed) and is left for the caller to refuse on.
    """
    t_correct = _correct_by_sample(treatment_run)
    c_correct = _correct_by_sample(control_run)
    paired_ids = sorted(t_correct.keys() & c_correct.keys())
    n = len(paired_ids)

    fd_correct = sum(1 for sid in paired_ids if t_correct[sid])
    sf_correct = sum(1 for sid in paired_ids if c_correct[sid])
    # Discordant pairs for McNemar: b = treatment right & control wrong; c = the reverse.
    b = sum(1 for sid in paired_ids if t_correct[sid] and not c_correct[sid])
    c = sum(1 for sid in paired_ids if not t_correct[sid] and c_correct[sid])

    fd_acc = fd_correct / n if n else 0.0
    sf_acc = sf_correct / n if n else 0.0
    delta = (b - c) / n if n else 0.0  # identical to fd_acc - sf_acc over the paired set
    delta_ci = _mcnemar_delta_ci(b, c, n)

    note = (
        "Positive delta = the family-different lock helps (a same-family verifier self-prefers and "
        "misses defects, per Panickssery 2024). Delta is PAIRED (McNemar) over the samples both "
        "arms measured; the CI is the Wald interval on the correlated-proportions difference. "
        "Meaningful only with REAL models; the OFFLINE control uses a self-preferring MOCK to "
        "prove the wiring deterministically — its positive delta is machinery, NOT self-preference "
        "evidence."
    )
    return FamilyAB(
        family_different_accuracy=fd_acc,
        same_family_accuracy=sf_acc,
        delta=delta,
        note=note,
        n_paired=n,
        family_different_correct=fd_correct,
        same_family_correct=sf_correct,
        delta_ci=delta_ci,
        family_different_model_ids=sorted(set(treatment_run.resolved_model_ids)),
        same_family_model_ids=sorted(set(control_run.resolved_model_ids)),
    )


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
