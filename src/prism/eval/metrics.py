"""Pure-Python evaluation metrics for the prism calibration benchmark.

No numpy/scipy — each metric is a closed-form formula over small inputs, so the eval pack adds zero
heavy deps (lean-deps ethos). Grounding (see ``design/07-slice1-calibration.md``; [V]=web-verified,
[C]=canonical/pending-reverify):

- Chance-corrected agreement, not raw overlap: Cohen's kappa (Cohen 1960 [C]); Krippendorff's alpha
  for >=3 raters + missing data (Hayes & Krippendorff 2007 [C]). PABAK guards the kappa paradox
  under skewed prevalence (Byrt/Bishop/Carlin 1993 [C]).
- MCC over F1/accuracy under class imbalance (Chicco & Jurman, BMC Genomics 2020 [C]).
- Calibration as a separate axis: ECE + Brier (Guo et al., ICML 2017 [C]).
- Submodular coverage gain operationalizes "union beats any single lens" (Nemhauser/Wolsey/Fisher
  1978 [C]); diversity (rho) alone weakly predicts ensemble gain, so coverage-gain is the
  PRIMARY collapse signal (Kuncheva & Whitaker, Machine Learning 2003 [C]).
- AST/tree code similarity beats token overlap (Song et al., ACL 2024, arXiv:2404.08817 [V]).

The finding-set rho prism uses at runtime lives in ``prism.core.submodularity`` (re-exported).
"""

from __future__ import annotations

import ast
import math
from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field

from prism.core.submodularity import jaccard_similarity  # re-exported: finding-set rho

__all__ = [
    "jaccard_similarity",
    "Confusion",
    "QualityMetrics",
    "confusion_matrix",
    "quality_metrics",
    "cohen_kappa",
    "pabak",
    "krippendorff_alpha",
    "expected_calibration_error",
    "brier_score",
    "CoverageGain",
    "coverage_gain",
    "ast_node_similarity",
    "wilson_interval",
]


# --- Classification quality (per-lens verifier quality) ---


@dataclass(frozen=True)
class Confusion:
    """A binary confusion matrix. Positive = the sample IS defective / should be flagged."""

    tp: int
    tn: int
    fp: int
    fn: int

    @property
    def n(self) -> int:
        return self.tp + self.tn + self.fp + self.fn


def confusion_matrix(y_true: Sequence[bool], y_pred: Sequence[bool]) -> Confusion:
    """Build a confusion matrix from equal-length boolean truth/prediction sequences."""
    if len(y_true) != len(y_pred):
        raise ValueError(f"length mismatch: {len(y_true)} truth vs {len(y_pred)} pred")
    tp = tn = fp = fn = 0
    for t, p in zip(y_true, y_pred, strict=True):
        if t and p:
            tp += 1
        elif t and not p:
            fn += 1
        elif not t and p:
            fp += 1
        else:
            tn += 1
    return Confusion(tp=tp, tn=tn, fp=fp, fn=fn)


@dataclass(frozen=True)
class QualityMetrics:
    """Per-lens verifier quality. MCC + balanced accuracy lead; accuracy alone is never reported."""

    confusion: Confusion
    precision: float
    recall: float
    f1: float
    specificity: float
    balanced_accuracy: float
    mcc: float


def quality_metrics(y_true: Sequence[bool], y_pred: Sequence[bool]) -> QualityMetrics:
    """Compute precision/recall/F1/specificity/balanced-accuracy/MCC. Degenerate denoms -> 0.0."""
    c = confusion_matrix(y_true, y_pred)
    precision = c.tp / (c.tp + c.fp) if (c.tp + c.fp) else 0.0
    recall = c.tp / (c.tp + c.fn) if (c.tp + c.fn) else 0.0
    specificity = c.tn / (c.tn + c.fp) if (c.tn + c.fp) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    balanced_accuracy = (recall + specificity) / 2
    denom = math.sqrt(
        (c.tp + c.fp) * (c.tp + c.fn) * (c.tn + c.fp) * (c.tn + c.fn)
    )
    mcc = (c.tp * c.tn - c.fp * c.fn) / denom if denom else 0.0
    return QualityMetrics(
        confusion=c,
        precision=precision,
        recall=recall,
        f1=f1,
        specificity=specificity,
        balanced_accuracy=balanced_accuracy,
        mcc=mcc,
    )


# --- Inter-rater / inter-lens agreement (the diversity matrix) ---


def cohen_kappa(rater_a: Sequence[str], rater_b: Sequence[str]) -> float:
    """Cohen's kappa for two raters over nominal labels. Perfect-by-chance -> 0.0; identical -> 1.0.

    kappa = (p_o - p_e) / (1 - p_e). When p_e == 1 (a single category used by both), agreement is
    entirely chance-explained and kappa is conventionally 0.0 (no reliability beyond chance).
    """
    if len(rater_a) != len(rater_b):
        raise ValueError(f"length mismatch: {len(rater_a)} vs {len(rater_b)}")
    n = len(rater_a)
    if n == 0:
        return 0.0
    p_o = sum(1 for a, b in zip(rater_a, rater_b, strict=True) if a == b) / n
    count_a: Counter[str] = Counter(rater_a)
    count_b: Counter[str] = Counter(rater_b)
    categories = set(count_a) | set(count_b)
    p_e = sum((count_a[c] / n) * (count_b[c] / n) for c in categories)
    if math.isclose(p_e, 1.0):
        return 1.0 if math.isclose(p_o, 1.0) else 0.0
    return (p_o - p_e) / (1 - p_e)


def pabak(observed_agreement: float) -> float:
    """Prevalence-Adjusted Bias-Adjusted Kappa = 2*p_o - 1. Guards the kappa paradox under skew."""
    return 2 * observed_agreement - 1


def krippendorff_alpha(units: Sequence[Sequence[str | None]]) -> float | None:
    """Krippendorff's alpha (nominal) over ragged reliability data.

    ``units`` is one entry per item; each entry is the list of coder/lens values for that item, with
    ``None`` for a missing/abstained rating. Handles >=3 raters and missing data natively (the
    reason it's the headline diversity metric over Fleiss' kappa). Returns ``None`` if there is no
    pairable data. Perfect agreement -> 1.0.

    alpha = 1 - (n-1) * sum_{c!=k} o_ck / sum_{c!=k} n_c*n_k  (coincidence-matrix form).
    """
    o: dict[tuple[str, str], float] = defaultdict(float)
    for unit in units:
        vals = [v for v in unit if v is not None]
        m = len(vals)
        if m < 2:
            continue
        for i in range(m):
            for j in range(m):
                if i != j:
                    o[(vals[i], vals[j])] += 1.0 / (m - 1)
    if not o:
        return None
    n_c: dict[str, float] = defaultdict(float)
    for (c, _k), val in o.items():
        n_c[c] += val
    n = sum(n_c.values())
    if n < 2:
        return None
    observed_disagreement = sum(val for (c, k), val in o.items() if c != k)
    if math.isclose(observed_disagreement, 0.0):
        return 1.0  # all coders agree on every pairable unit
    expected_disagreement = (
        sum(n_c[c] * n_c[k] for c in n_c for k in n_c if c != k) / (n - 1)
    )
    if math.isclose(expected_disagreement, 0.0):
        return 1.0
    return 1.0 - observed_disagreement / expected_disagreement


# --- Confidence calibration (prism returns a confidence) ---


def expected_calibration_error(
    confidences: Sequence[float], correct: Sequence[bool], n_bins: int = 10
) -> float:
    """ECE: sum over confidence bins of |accuracy - mean confidence| weighted by bin population."""
    if len(confidences) != len(correct):
        raise ValueError("confidences and correct must be equal length")
    n = len(confidences)
    if n == 0:
        return 0.0
    if n_bins < 1:
        raise ValueError("n_bins must be >= 1")
    bin_total = [0] * n_bins
    bin_correct = [0] * n_bins
    bin_conf = [0.0] * n_bins
    for conf, is_correct in zip(confidences, correct, strict=True):
        c = min(max(conf, 0.0), 1.0)
        idx = min(int(c * n_bins), n_bins - 1)  # c == 1.0 lands in the last bin
        bin_total[idx] += 1
        bin_correct[idx] += 1 if is_correct else 0
        bin_conf[idx] += c
    ece = 0.0
    for b in range(n_bins):
        if bin_total[b] == 0:
            continue
        acc = bin_correct[b] / bin_total[b]
        avg_conf = bin_conf[b] / bin_total[b]
        ece += (bin_total[b] / n) * abs(acc - avg_conf)
    return ece


def brier_score(probabilities: Sequence[float], outcomes: Sequence[bool]) -> float:
    """Brier score (a proper scoring rule): mean squared error of probabilistic predictions."""
    if len(probabilities) != len(outcomes):
        raise ValueError("probabilities and outcomes must be equal length")
    n = len(probabilities)
    if n == 0:
        return 0.0
    total = sum(
        (p - (1.0 if o else 0.0)) ** 2 for p, o in zip(probabilities, outcomes, strict=True)
    )
    return total / n


# --- Submodular coverage gain (the PRIMARY collapse signal) ---


@dataclass(frozen=True)
class CoverageGain:
    """Does the union of lenses beat the best single lens? (submodular coverage)."""

    union_size: int
    best_single_lens: str | None
    best_single_size: int
    gain: int  # union_size - best_single_size; > 0 means the union genuinely adds coverage
    union_recall: float  # union_size / total_positives
    marginal_gains: list[tuple[str, int]] = field(default_factory=list)  # greedy order


def coverage_gain(
    caught_by_lens: dict[str, set[str]], total_positives: int
) -> CoverageGain:
    """Compute union coverage, best single lens, and the greedy marginal-gain curve.

    ``caught_by_lens`` maps lens name -> the set of positive-sample ids that lens correctly flagged.
    A lens whose greedy marginal gain is 0 is the operational definition of a REDUNDANT lens.
    """
    union: set[str] = set()
    for caught in caught_by_lens.values():
        union |= caught
    best_single_lens: str | None = None
    best_single_size = 0
    for lens, caught in caught_by_lens.items():
        if len(caught) > best_single_size or best_single_lens is None:
            best_single_lens = lens
            best_single_size = len(caught)
    # Greedy marginal-gain curve: repeatedly add the lens contributing the most NEW catches.
    remaining = dict(caught_by_lens)
    covered: set[str] = set()
    marginal: list[tuple[str, int]] = []
    while remaining:
        best_lens = max(remaining, key=lambda name: len(remaining[name] - covered))
        new = remaining[best_lens] - covered
        marginal.append((best_lens, len(new)))
        covered |= remaining[best_lens]
        del remaining[best_lens]
    union_recall = len(union) / total_positives if total_positives else 0.0
    return CoverageGain(
        union_size=len(union),
        best_single_lens=best_single_lens,
        best_single_size=best_single_size,
        gain=len(union) - best_single_size,
        union_recall=union_recall,
        marginal_gains=marginal,
    )


# --- Code-structure similarity (forward-looking: code-suggestion rho) ---


def ast_node_similarity(code_a: str, code_b: str) -> float | None:
    """Structural similarity of two Python snippets via AST node-type multiset Jaccard.

    Returns ``None`` if either snippet does not parse (so a caller can fall back to token overlap).
    Two snippets differing only in identifier names / whitespace score ~1.0, where string overlap
    would call them dissimilar (Song et al. 2024 — structure beats tokens for code). This is a
    lightweight stdlib stand-in for full tree-edit distance (Zhang-Shasha/APTED), adequate for
    detecting when two lenses flag the structurally-same issue; upgrade to APTED if needed.
    """
    try:
        tree_a = ast.parse(code_a)
        tree_b = ast.parse(code_b)
    except (SyntaxError, ValueError):
        return None
    types_a: Counter[str] = Counter(type(n).__name__ for n in ast.walk(tree_a))
    types_b: Counter[str] = Counter(type(n).__name__ for n in ast.walk(tree_b))
    if not types_a and not types_b:
        return 1.0
    intersection = sum((types_a & types_b).values())
    union = sum((types_a | types_b).values())
    return intersection / union if union else 1.0


# --- Estimation helper (honest CIs on small corpora) ---


def wilson_interval(successes: int, total: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score interval for a binomial proportion (a recall/precision point's CI).

    Used to report the honest +/- band on per-lens recall at the corpus size actually built, rather
    than a bare point estimate. z=1.96 -> 95%.
    """
    if total == 0:
        return (0.0, 0.0)
    p = successes / total
    denom = 1 + z * z / total
    center = (p + z * z / (2 * total)) / denom
    margin = (z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total))) / denom
    return (max(0.0, center - margin), min(1.0, center + margin))
