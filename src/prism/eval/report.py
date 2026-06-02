"""Turn an ``EvalRun`` into measured metrics + a rendered report (markdown / json).

Aggregates the N runs (majority lens decision, modal verdict, mean confidence), then computes
per-lens precision/recall/MCC over each lens's target class, the inter-lens diversity matrix
(Krippendorff alpha + pairwise Cohen kappa + the runtime finding-set rho), the submodular
coverage-gain, artifact-level verdict accuracy, and confidence calibration (ECE/Brier). Every recall
is paired with a Wilson interval so the v1 small-N uncertainty is explicit.
"""

from __future__ import annotations

import json
import statistics
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field

from prism.eval.calibrate import FamilyAB, rho_threshold_sweep
from prism.eval.metrics import (
    brier_score,
    cohen_kappa,
    coverage_gain,
    expected_calibration_error,
    krippendorff_alpha,
    quality_metrics,
    wilson_interval,
)
from prism.eval.runner import EvalRun, RunRecord

_LLM_LENSES = ("contract_completeness", "cross_boundary", "invariant", "groundedness")
_OFF_ACCEPT = {"refuse", "revise", "escalate"}


@dataclass
class LensReport:
    lens: str
    n: int  # samples targeting this lens (positives + clean counterparts)
    positives: int
    recall: float
    recall_ci: tuple[float, float]
    precision: float
    specificity: float
    mcc: float
    balanced_accuracy: float


@dataclass
class ReportData:
    verifier_label: str
    caller_family: str
    n_runs: int
    n_samples: int
    counts_by_class: dict[str, int]
    per_lens: list[LensReport]
    krippendorff_alpha: float | None
    pairwise_kappa: dict[str, float]
    mean_pairwise_rho: dict[str, float]
    coverage_union_recall: float
    coverage_gain: int
    coverage_best_single: str | None
    coverage_marginal: list[tuple[str, int]]
    verdict_accuracy_overall: float
    verdict_accuracy_by_class: dict[str, float]
    ece: float
    brier: float
    verdict_consistency: float
    rho_baseline_accuracy: float
    rho_best_cutoff: float | None
    rho_note: str
    notes: list[str] = field(default_factory=list)
    family_ab: FamilyAB | None = None  # set by the CLI when --family-ab runs the control


def _group_by_sample(run: EvalRun) -> dict[str, list[RunRecord]]:
    grouped: dict[str, list[RunRecord]] = defaultdict(list)
    for r in run.records:
        grouped[r.sample_id].append(r)
    return grouped


def _majority_fail(records: list[RunRecord], lens: str) -> bool | None:
    """Did ``lens`` flag (FAIL) on a majority of the runs where it produced an outcome?"""
    outcomes = [r.per_lens[lens] for r in records if lens in r.per_lens]
    if not outcomes:
        return None
    return sum(1 for o in outcomes if o == "fail") * 2 > len(outcomes)


def _modal_verdict(records: list[RunRecord]) -> str:
    return Counter(r.verdict for r in records).most_common(1)[0][0]


def summarize(run: EvalRun) -> ReportData:
    """Compute all measured metrics from the raw run records."""
    by_sample = _group_by_sample(run)

    # Per-sample aggregates (stable over N runs).
    samp_verdict: dict[str, str] = {}
    samp_conf: dict[str, float] = {}
    samp_fail: dict[str, dict[str, bool]] = {}
    consistencies: list[float] = []
    for sid, recs in by_sample.items():
        modal = _modal_verdict(recs)
        samp_verdict[sid] = modal
        samp_conf[sid] = statistics.fmean(r.confidence for r in recs)
        samp_fail[sid] = {
            lens: bool(_majority_fail(recs, lens))
            for lens in _LLM_LENSES
            if _majority_fail(recs, lens) is not None
        }
        consistencies.append(sum(1 for r in recs if r.verdict == modal) / len(recs))

    # Per-lens quality over each lens's target class (buggy + clean counterparts share target_lens).
    per_lens: list[LensReport] = []
    for lens in _LLM_LENSES:
        rel = [s for s in run.samples.values() if s.target_lens == lens]
        if not rel:
            continue
        y_true = [s.positive for s in rel]
        y_pred = [samp_fail.get(s.id, {}).get(lens, False) for s in rel]
        q = quality_metrics(y_true, y_pred)
        per_lens.append(
            LensReport(
                lens=lens,
                n=len(rel),
                positives=sum(y_true),
                recall=q.recall,
                recall_ci=wilson_interval(q.confusion.tp, q.confusion.tp + q.confusion.fn),
                precision=q.precision,
                specificity=q.specificity,
                mcc=q.mcc,
                balanced_accuracy=q.balanced_accuracy,
            )
        )

    # Diversity matrix over samples with a full 4-lens decision (code/tool path).
    units: list[list[str | None]] = []
    decisions: dict[str, list[str]] = {lens: [] for lens in _LLM_LENSES}
    for sid, fails in samp_fail.items():
        if all(lens in fails for lens in _LLM_LENSES):
            units.append(["fail" if fails[lens] else "ok" for lens in _LLM_LENSES])
            for lens in _LLM_LENSES:
                decisions[lens].append("fail" if fails[lens] else "ok")
    alpha = krippendorff_alpha(units) if units else None
    pairwise_kappa: dict[str, float] = {}
    for i in range(len(_LLM_LENSES)):
        for j in range(i + 1, len(_LLM_LENSES)):
            a, b = _LLM_LENSES[i], _LLM_LENSES[j]
            if decisions[a] and decisions[b]:
                pairwise_kappa[f"{a},{b}"] = cohen_kappa(decisions[a], decisions[b])

    # Mean runtime finding-set rho per lens-pair, across all runs.
    rho_acc: dict[str, list[float]] = defaultdict(list)
    for r in run.records:
        for pair, val in r.pairwise_rho.items():
            rho_acc[pair].append(val)
    mean_rho = {pair: statistics.fmean(vals) for pair, vals in rho_acc.items()}

    # Submodular coverage gain over code/tool positives.
    caught: dict[str, set[str]] = {lens: set() for lens in _LLM_LENSES}
    positive_ids: set[str] = set()
    for sid, s in run.samples.items():
        if s.positive and s.artifact_type != "citations":
            positive_ids.add(sid)
            for lens in _LLM_LENSES:
                if samp_fail.get(sid, {}).get(lens):
                    caught[lens].add(sid)
    cg = coverage_gain(caught, len(positive_ids)) if positive_ids else None

    # Verdict accuracy (flag-vs-accept correctness) overall + per class.
    correct: dict[str, bool] = {}
    for sid, s in run.samples.items():
        v = samp_verdict[sid]
        correct[sid] = (v in _OFF_ACCEPT) if s.positive else (v == "accept")
    by_class_correct: dict[str, list[bool]] = defaultdict(list)
    for sid, s in run.samples.items():
        by_class_correct[s.artifact_type].append(correct[sid])
    overall = statistics.fmean(correct.values()) if correct else 0.0
    acc_by_class = {cls: statistics.fmean(vals) for cls, vals in by_class_correct.items()}

    # Calibration: confidence vs flag-correctness.
    ids = list(run.samples)
    ece = expected_calibration_error([samp_conf[i] for i in ids], [correct[i] for i in ids])
    brier = brier_score([samp_conf[i] for i in ids], [correct[i] for i in ids])

    counts_by_class: Counter[str] = Counter(s.artifact_type for s in run.samples.values())
    notes: list[str] = []
    if "mock" in run.verifier_label or "offline" in run.verifier_label:
        notes.append(
            "OFFLINE/MOCK verifier - exercises the pipeline but is NOT a real measurement."
        )
    min_pos = min((lr.positives for lr in per_lens), default=0)
    if min_pos < 100:
        notes.append(
            f"v1 small-N corpus (min {min_pos} positives/lens < 100); recall CIs wide (see Wilson)."
        )

    sweep = rho_threshold_sweep(run)

    return ReportData(
        verifier_label=run.verifier_label or "(unlabeled)",
        caller_family=run.caller_family,
        n_runs=run.n_runs,
        n_samples=len(run.samples),
        counts_by_class=dict(counts_by_class),
        per_lens=per_lens,
        krippendorff_alpha=alpha,
        pairwise_kappa=pairwise_kappa,
        mean_pairwise_rho=mean_rho,
        coverage_union_recall=cg.union_recall if cg else 0.0,
        coverage_gain=cg.gain if cg else 0,
        coverage_best_single=cg.best_single_lens if cg else None,
        coverage_marginal=cg.marginal_gains if cg else [],
        verdict_accuracy_overall=overall,
        verdict_accuracy_by_class=acc_by_class,
        ece=ece,
        brier=brier,
        verdict_consistency=statistics.fmean(consistencies) if consistencies else 1.0,
        rho_baseline_accuracy=sweep.baseline_accuracy,
        rho_best_cutoff=sweep.best_cutoff,
        rho_note=sweep.note,
        notes=notes,
    )


def render_json(report: ReportData) -> str:
    return json.dumps(asdict(report), indent=2, default=str)


def _fmt(x: float) -> str:
    return f"{x:.3f}"


def render_markdown(report: ReportData) -> str:
    lines: list[str] = []
    lines.append("# Prism calibration benchmark - results")
    lines.append("")
    lines.append(
        f"Verifier: **{report.verifier_label}** | caller family: {report.caller_family} | "
        f"runs/sample: {report.n_runs} | samples: {report.n_samples} "
        f"({', '.join(f'{k}={v}' for k, v in report.counts_by_class.items())})"
    )
    lines.append("")
    for note in report.notes:
        lines.append(f"> WARNING: {note}")
    if report.notes:
        lines.append("")

    lines.append("## Per-lens quality (on each lens's target class)")
    lines.append("")
    lines.append("| Lens | n | pos | recall (95% CI) | precision | specificity | MCC | bal-acc |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for lr in report.per_lens:
        ci = f"{_fmt(lr.recall)} [{_fmt(lr.recall_ci[0])}, {_fmt(lr.recall_ci[1])}]"
        lines.append(
            f"| {lr.lens} | {lr.n} | {lr.positives} | {ci} | {_fmt(lr.precision)} | "
            f"{_fmt(lr.specificity)} | {_fmt(lr.mcc)} | {_fmt(lr.balanced_accuracy)} |"
        )
    lines.append("")

    lines.append("## Diversity (do the lenses give independent signal?)")
    lines.append("")
    alpha = "n/a" if report.krippendorff_alpha is None else _fmt(report.krippendorff_alpha)
    lines.append(f"- **Krippendorff alpha (lens decisions): {alpha}** (lower = more independent)")
    if report.pairwise_kappa:
        lines.append("- Pairwise Cohen kappa:")
        for pair, k in sorted(report.pairwise_kappa.items()):
            lines.append(f"  - {pair}: {_fmt(k)}")
    if report.mean_pairwise_rho:
        lines.append("- Mean finding-set rho (the runtime submodularity metric):")
        for pair, rho in sorted(report.mean_pairwise_rho.items()):
            flag = "  <-- > 0.25" if rho > 0.25 else ""
            lines.append(f"  - {pair}: {_fmt(rho)}{flag}")
    lines.append("")

    lines.append("## Submodular coverage (does the union beat the best single lens?)")
    lines.append("")
    lines.append(f"- Union recall over defects: **{_fmt(report.coverage_union_recall)}**")
    lines.append(
        f"- Coverage gain (union - best single): **{report.coverage_gain}** "
        f"(best single lens: {report.coverage_best_single})"
    )
    if report.coverage_marginal:
        chain = " -> ".join(f"{lens}(+{n})" for lens, n in report.coverage_marginal)
        lines.append(f"- Greedy marginal gain: {chain}  (a +0 lens is redundant)")
    lines.append("")

    lines.append("## Verdict accuracy & calibration")
    lines.append("")
    overall = _fmt(report.verdict_accuracy_overall)
    lines.append(f"- Overall verdict accuracy (flag vs accept): **{overall}**")
    for cls, acc in sorted(report.verdict_accuracy_by_class.items()):
        lines.append(f"  - {cls}: {_fmt(acc)}")
    ece, brier = _fmt(report.ece), _fmt(report.brier)
    lines.append(f"- Confidence calibration: ECE **{ece}**, Brier **{brier}**")
    lines.append(f"- Verdict consistency across runs: {_fmt(report.verdict_consistency)}")
    lines.append("")

    lines.append("## Submodularity-threshold (rho) calibration")
    lines.append("")
    lines.append(f"- Baseline accuracy (no rho gating): **{_fmt(report.rho_baseline_accuracy)}**")
    cutoff = "n/a" if report.rho_best_cutoff is None else _fmt(report.rho_best_cutoff)
    lines.append(f"- Best cutoff (acc*coverage): **{cutoff}** (runtime default stays 0.25)")
    lines.append(f"- {report.rho_note}")
    lines.append("")

    ab = report.family_ab
    if ab is not None:
        lines.append("## Family-different vs same-family (Lock 1 A/B)")
        lines.append("")
        lines.append(f"- Family-different accuracy: **{_fmt(ab.family_different_accuracy)}**")
        lines.append(f"- Same-family control accuracy: **{_fmt(ab.same_family_accuracy)}**")
        lines.append(f"- Delta (family-different - same-family): **{_fmt(ab.delta)}**")
        lines.append(f"- {ab.note}")
        lines.append("")
    return "\n".join(lines)
