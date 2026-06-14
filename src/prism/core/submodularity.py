"""Submodularity calculator.

Lock 4: Compute pairwise Jaccard rho across lens findings.
Refuse if rho exceeds threshold (lenses collapsed to redundant signal).

Default threshold: rho <= 0.25 per pair.
Empirical basis: Rajan 2025 (arXiv:2511.16708), rho in [0.05, 0.25] on 99 code samples.
Caveat: Rajan doesn't specify metric type; our Jaccard-on-file:line-finding-sets
is a documented extrapolation.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from prism.core.types import Finding, LensResult


def _resolve_rho_max_default() -> float:
    """The canonical runtime LENS_COLLAPSE threshold (ρ).

    0.25 is the shipped default — Rajan 2025 (arXiv:2511.16708) observed ρ ∈ [0.05, 0.25] across
    four agents on 99 code samples; a pair exceeding it is treated as collapsed to redundant signal.
    ``PRISM_RHO_MAX`` overrides it (a deployment that calibrated its own cutoff on labeled data);
    a malformed/non-finite override is ignored so a bad env var never silently weakens the gate.
    """
    raw = os.environ.get("PRISM_RHO_MAX")
    if raw is None:
        return 0.25
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return 0.25
    # Only accept a sane probability-domain threshold; otherwise keep the shipped default.
    if value != value or value < 0.0 or value > 1.0:  # NaN or out of [0, 1]
        return 0.25
    return value


# Canonical named constant for the runtime LENS_COLLAPSE threshold (ρ). EVS-B-005: every site that
# needs the default ρ cutoff (engine.py, this module, the eval sweep) imports THIS, so the value is
# defined once. ``PRISM_RHO_MAX`` overrides the default 0.25; see ``_resolve_rho_max_default``.
RHO_MAX_DEFAULT = _resolve_rho_max_default()

# Backward-compatible alias (pre-EVS-B-005 name). Kept so existing imports / tests keep resolving;
# both names point at the one canonical value.
DEFAULT_RHO_THRESHOLD = RHO_MAX_DEFAULT


@dataclass(frozen=True)
class SubmodularityResult:
    """Result of submodularity check."""

    pairwise_rho: dict[str, float]
    collapsed_pairs: list[str]
    passed: bool


def _finding_key(finding: Finding) -> tuple[str | None, int | None, str]:
    """Create a hashable key from a finding's (file, line, category)."""
    return (finding.file, finding.line, finding.category)


def jaccard_similarity(set_a: set[tuple[str | None, int | None, str]],
                       set_b: set[tuple[str | None, int | None, str]]) -> float:
    """Compute Jaccard similarity between two finding sets.

    Returns 0.0 if both sets are empty (vacuously independent).
    """
    if not set_a and not set_b:
        return 0.0

    intersection = set_a & set_b
    union = set_a | set_b

    if not union:
        return 0.0

    return len(intersection) / len(union)


def compute_pairwise_rho(
    lens_results: list[LensResult],
    thresholds: dict[str, float] | None = None,
    default_threshold: float = DEFAULT_RHO_THRESHOLD,
) -> SubmodularityResult:
    """Compute pairwise Jaccard rho across all lens-result pairs.

    Args:
        lens_results: Results from lens execution.
        thresholds: Optional per-pair threshold overrides (e.g., {"L1,L2": 0.30}).
        default_threshold: Default threshold for pairs without override.

    Returns:
        SubmodularityResult with rho values and collapse detection.
    """
    if len(lens_results) < 2:
        return SubmodularityResult(pairwise_rho={}, collapsed_pairs=[], passed=True)

    # Build finding sets per lens
    finding_sets: dict[str, set[tuple[str | None, int | None, str]]] = {}
    for result in lens_results:
        keys = {_finding_key(f) for f in result.findings}
        finding_sets[result.lens] = keys

    pairwise_rho: dict[str, float] = {}
    collapsed_pairs: list[str] = []

    # Compute all pairs
    lenses = list(finding_sets.keys())
    for i in range(len(lenses)):
        for j in range(i + 1, len(lenses)):
            pair_key = f"{lenses[i]},{lenses[j]}"
            rho = jaccard_similarity(finding_sets[lenses[i]], finding_sets[lenses[j]])
            pairwise_rho[pair_key] = rho

            # Check threshold
            threshold = (thresholds or {}).get(pair_key, default_threshold)
            if rho > threshold:
                collapsed_pairs.append(pair_key)

    return SubmodularityResult(
        pairwise_rho=pairwise_rho,
        collapsed_pairs=collapsed_pairs,
        passed=len(collapsed_pairs) == 0,
    )
