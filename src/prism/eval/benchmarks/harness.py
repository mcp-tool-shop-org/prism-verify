"""CodeJudgeBench harness (F-01 sub-build 3B) — run prism over the pairwise items + summarize.

prism is single-artifact (``engine.verify`` over ONE artifact), but CodeJudgeBench is PAIRWISE.
``run_codejudgebench`` bridges the two: for each item it verifies the CHOSEN code and the REJECTED
code separately (each as a ``code`` artifact with the item's question as intent), then reduces the
two single-artifact verdicts to a preference via ``calibrate.pairwise_prefer`` (its FIRST caller —
it had zero before). A result is CORRECT iff prism prefers the CHOSEN side.

Two robustness measures the CodeJudgeBench paper calls for (it reports that response ORDER
"substantially impacts accuracy"):
  * BOTH ORDERS — pairwise_prefer is run chosen-first AND rejected-first; POSITION-CONSISTENCY is
    how often the two orders agree. Low consistency = an order-biased verifier (a real defect).
  * N>=3 runs — single-artifact verdict variance control (matching the corpus runner's N>=3).

TIE handling (load-bearing): pairwise_prefer can return 'tie' (equal verdict rank AND equal
confidence). On a KNOWN good-vs-bad pair a tie is a real DISCRIMINATION FAILURE, so it is counted
WRONG in the headline accuracy AND reported separately as a tie-rate. Every accuracy point carries a
Wilson CI (the small-N honesty the corpus report uses).
"""

# ruff: noqa: E501 — the reduction-contract docstrings (how single-artifact verdicts collapse to a
# pairwise preference, tie/order handling) are clearer unwrapped, as in corpus.py / realbug.py.
from __future__ import annotations

import statistics
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field

from prism.core.types import (
    Artifact,
    ArtifactType,
    Budget,
    CallerContext,
    ModelFamily,
    VerifyError,
    VerifyRequest,
)
from prism.eval.benchmarks.codejudgebench import CJBItem
from prism.eval.calibrate import pairwise_prefer
from prism.eval.metrics import wilson_interval

# Pairwise outcome relative to the CHOSEN side. "chosen" = prism preferred the chosen code (correct);
# "rejected" = it preferred the rejected code (wrong); "tie" = no discrimination (counted wrong).
PairOutcome = str  # "chosen" | "rejected" | "tie"


@dataclass(frozen=True)
class CJBResult:
    """One CodeJudgeBench item's adjudication, reduced from prism's two single-artifact verdicts.

    ``outcome`` is the modal pairwise outcome across the N runs in CHOSEN-first orientation.
    ``correct`` is ``outcome == 'chosen'`` (a tie is NOT correct). ``orders_agree`` is whether
    chosen-first and rejected-first produced the SAME side preference (position consistency).
    ``unavailable`` marks an item where prism could not adjudicate one/both sides (excluded from
    accuracy, mirroring the corpus runner's EVL-A-001 rule).
    """

    item_id: str
    task: str
    producer: str
    outcome: PairOutcome
    correct: bool
    is_tie: bool
    orders_agree: bool
    unavailable: bool = False


@dataclass
class _Cell:
    """Mutable accumulator for an accuracy bucket (overall / per-task / per-producer)."""

    correct: int = 0
    total: int = 0
    ties: int = 0


@dataclass(frozen=True)
class AccuracyPoint:
    """An accuracy bucket with its tie-rate and a Wilson CI (small-N honesty)."""

    label: str
    correct: int
    total: int
    accuracy: float
    accuracy_ci: tuple[float, float]
    ties: int
    tie_rate: float


@dataclass(frozen=True)
class CJBSummary:
    """Summarized CodeJudgeBench results: overall + per-task + per-producer accuracy, the
    position-consistency rate, the tie-rate, each accuracy with a Wilson CI."""

    n_items: int  # items with a genuine (available) measurement — the accuracy denominator
    n_unavailable: int  # items excluded because prism could not adjudicate (EVL-A-001)
    overall: AccuracyPoint
    per_task: list[AccuracyPoint]
    per_producer: list[AccuracyPoint]
    position_consistency: float  # fraction of available items whose two orders agreed
    position_consistency_ci: tuple[float, float]
    notes: list[str] = field(default_factory=list)


def _intent_for(item: CJBItem) -> str:
    """The verify intent for one item: the question, plus the context (starter/wrong code) if any.

    Both code sides are verified against the SAME intent, so the only thing that differs between the
    two verify calls is the artifact — exactly what a pairwise judgment needs.
    """
    if item.context:
        return f"{item.question}\n\n[context / starter code]\n{item.context}"
    return item.question


def _build_request(
    item: CJBItem, code: str, caller_family: str, max_latency_ms: int
) -> VerifyRequest:
    return VerifyRequest(
        artifact=Artifact(type=ArtifactType.CODE, content=code),
        intent=_intent_for(item),
        caller=CallerContext(model_family=ModelFamily(caller_family), model_id="codejudgebench"),
        budget=Budget(max_latency_ms=max_latency_ms),
    )


def _prefer_chosen(
    chosen_verdict: str,
    chosen_conf: float,
    rejected_verdict: str,
    rejected_conf: float,
    *,
    chosen_first: bool,
) -> PairOutcome:
    """Reduce the two single-artifact verdicts to a CHOSEN-relative outcome via pairwise_prefer.

    ``chosen_first`` controls the ARGUMENT ORDER passed to pairwise_prefer (the position-bias probe):
    when True, chosen is 'a' and rejected is 'b'; when False the arguments are swapped. The returned
    'a'/'b' is then mapped back to chosen/rejected so the outcome is order-independent in MEANING
    (only the verifier's order-SENSITIVITY shows up, as a disagreement between the two orientations).
    """
    if chosen_first:
        pick = pairwise_prefer(chosen_verdict, chosen_conf, rejected_verdict, rejected_conf)
        return {"a": "chosen", "b": "rejected", "tie": "tie"}[pick]
    pick = pairwise_prefer(rejected_verdict, rejected_conf, chosen_verdict, chosen_conf)
    return {"a": "rejected", "b": "chosen", "tie": "tie"}[pick]


async def run_codejudgebench(
    engine: object,
    items: Sequence[CJBItem],
    *,
    caller_family: str = "anthropic",
    n_runs: int = 3,
    both_orders: bool = True,
    max_latency_ms: int = 30000,
) -> list[CJBResult]:
    """Run prism over each pairwise item and reduce to a CHOSEN-relative outcome per item.

    For each item: verify the CHOSEN code and the REJECTED code ``n_runs`` times each (N>=3 variance
    control), take each side's modal verdict + mean confidence over its GENUINE runs, then reduce via
    pairwise_prefer. With ``both_orders`` the reduction runs chosen-first AND rejected-first; the
    item's ``outcome`` is the chosen-first modal result and ``orders_agree`` records whether the two
    orientations agreed (position consistency). If either side is verifier-unavailable on EVERY run,
    the item is marked ``unavailable`` and excluded from accuracy (EVL-A-001 parity).

    ``engine`` is typed ``object`` so the harness does not hard-import the heavy engine here; it must
    expose an awaitable ``verify(VerifyRequest) -> VerifyResponse | VerifyError`` (the prism engine
    and the offline ``MockProvider``-backed engine both do).
    """
    if n_runs < 1:
        raise ValueError("n_runs must be >= 1")

    async def _side(item: CJBItem, code: str) -> tuple[str, float] | None:
        """Modal verdict + mean confidence over genuine runs for ONE code side, or None if every run
        was verifier-unavailable (a structural VerifyError)."""
        verdicts: list[str] = []
        confs: list[float] = []
        for _ in range(n_runs):
            req = _build_request(item, code, caller_family, max_latency_ms)
            result = await engine.verify(req)  # type: ignore[attr-defined]
            if isinstance(result, VerifyError):
                continue  # unavailable run — no genuine verdict (EVL-A-001)
            verdicts.append(result.verdict.value)
            confs.append(result.confidence)
        if not verdicts:
            return None
        modal = max(set(verdicts), key=lambda v: (verdicts.count(v), v))
        return modal, statistics.fmean(confs)

    results: list[CJBResult] = []
    for item in items:
        chosen = await _side(item, item.chosen_code)
        rejected = await _side(item, item.rejected_code)
        if chosen is None or rejected is None:
            results.append(
                CJBResult(
                    item_id=item.item_id,
                    task=item.task,
                    producer=item.producer,
                    outcome="tie",
                    correct=False,
                    is_tie=False,
                    orders_agree=True,
                    unavailable=True,
                )
            )
            continue
        cv, cc = chosen
        rv, rc = rejected
        chosen_first = _prefer_chosen(cv, cc, rv, rc, chosen_first=True)
        if both_orders:
            rejected_first = _prefer_chosen(cv, cc, rv, rc, chosen_first=False)
            orders_agree = chosen_first == rejected_first
        else:
            orders_agree = True
        results.append(
            CJBResult(
                item_id=item.item_id,
                task=item.task,
                producer=item.producer,
                outcome=chosen_first,
                correct=chosen_first == "chosen",  # a TIE is NOT correct (counted wrong)
                is_tie=chosen_first == "tie",
                orders_agree=orders_agree,
                unavailable=False,
            )
        )
    return results


def _point(label: str, cell: _Cell) -> AccuracyPoint:
    acc = cell.correct / cell.total if cell.total else 0.0
    return AccuracyPoint(
        label=label,
        correct=cell.correct,
        total=cell.total,
        accuracy=acc,
        accuracy_ci=wilson_interval(cell.correct, cell.total),
        ties=cell.ties,
        tie_rate=cell.ties / cell.total if cell.total else 0.0,
    )


def summarize_codejudgebench(results: list[CJBResult]) -> CJBSummary:
    """Overall + per-task + per-producer accuracy, position-consistency, tie-rate; each with a CI.

    Accuracy is over AVAILABLE items only (an item prism could not adjudicate on either side is
    excluded — EVL-A-001 parity — and counted in ``n_unavailable`` / disclosed in notes, never
    silently scored wrong). A TIE counts as WRONG in accuracy (correct=False) and is ALSO reported in
    the tie-rate. Position-consistency is the fraction of available items whose two orders agreed.
    """
    available = [r for r in results if not r.unavailable]
    n_unavailable = len(results) - len(available)

    overall = _Cell()
    by_task: dict[str, _Cell] = defaultdict(_Cell)
    by_producer: dict[str, _Cell] = defaultdict(_Cell)
    agree = 0
    for r in available:
        overall.total += 1
        overall.correct += 1 if r.correct else 0
        overall.ties += 1 if r.is_tie else 0
        ct = by_task[r.task]
        ct.total += 1
        ct.correct += 1 if r.correct else 0
        ct.ties += 1 if r.is_tie else 0
        cp = by_producer[r.producer]
        cp.total += 1
        cp.correct += 1 if r.correct else 0
        cp.ties += 1 if r.is_tie else 0
        agree += 1 if r.orders_agree else 0

    n_avail = len(available)
    position_consistency = agree / n_avail if n_avail else 0.0
    notes: list[str] = []
    if n_unavailable:
        notes.append(
            f"{n_unavailable} of {len(results)} item(s) were verifier-unavailable on a side and "
            "excluded from accuracy (structural error, no real verdict)."
        )
    if overall.ties:
        notes.append(
            f"{overall.ties} item(s) were TIES (pairwise_prefer could not discriminate); a tie on a "
            "known good-vs-bad pair is a real discrimination failure and is counted WRONG in "
            "accuracy (also reported as tie-rate)."
        )
    if n_avail < 100:
        notes.append(
            f"small-N: {n_avail} scored item(s) < 100; accuracy CIs are wide (see Wilson). The "
            "published RESULTS.md number needs a full-split run."
        )
    return CJBSummary(
        n_items=n_avail,
        n_unavailable=n_unavailable,
        overall=_point("overall", overall),
        per_task=[_point(t, by_task[t]) for t in sorted(by_task)],
        per_producer=[_point(p, by_producer[p]) for p in sorted(by_producer)],
        position_consistency=position_consistency,
        position_consistency_ci=wilson_interval(agree, n_avail),
        notes=notes,
    )
