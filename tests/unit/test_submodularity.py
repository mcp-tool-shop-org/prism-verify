"""Tests for submodularity calculator (Lock 4)."""

import pytest

from prism.core.submodularity import (
    compute_pairwise_rho,
    jaccard_similarity,
)
from prism.core.types import Finding, LensOutcome, LensResult


class TestJaccardSimilarity:
    def test_identical_sets(self):
        s = {("file.py", 1, "bug"), ("file.py", 2, "bug")}
        assert jaccard_similarity(s, s) == 1.0

    def test_disjoint_sets(self):
        a = {("a.py", 1, "bug")}
        b = {("b.py", 2, "style")}
        assert jaccard_similarity(a, b) == 0.0

    def test_partial_overlap(self):
        a = {("f.py", 1, "bug"), ("f.py", 2, "bug")}
        b = {("f.py", 1, "bug"), ("f.py", 3, "style")}
        # Intersection: 1 element, Union: 3 elements
        assert jaccard_similarity(a, b) == pytest.approx(1 / 3)

    def test_empty_sets(self):
        assert jaccard_similarity(set(), set()) == 0.0

    def test_one_empty(self):
        a = {("f.py", 1, "bug")}
        assert jaccard_similarity(a, set()) == 0.0


class TestComputePairwiseRho:
    def _make_result(self, lens_name: str, findings: list[tuple]) -> LensResult:
        return LensResult(
            lens=lens_name,
            model_family="google",
            model_id="gemini-2.5-pro",
            outcome=LensOutcome.FAIL,
            findings=[
                Finding(file=f, line=lineno, category=c, evidence="test")
                for f, lineno, c in findings
            ],
            confidence=0.8,
        )

    def test_independent_lenses_pass(self):
        """Lenses with disjoint findings should pass."""
        results = [
            self._make_result("L1", [("a.py", 1, "missing_clause")]),
            self._make_result("L2", [("b.py", 5, "pii_leak")]),
            self._make_result("L3", [("c.py", 10, "invariant_violation")]),
        ]
        sub = compute_pairwise_rho(results)
        assert sub.passed is True
        assert all(v == 0.0 for v in sub.pairwise_rho.values())

    def test_identical_findings_collapse(self):
        """Lenses with identical findings should trigger LENS_COLLAPSE."""
        findings = [("file.py", 1, "bug"), ("file.py", 2, "bug")]
        results = [
            self._make_result("L1", findings),
            self._make_result("L2", findings),
            self._make_result("L3", [("other.py", 99, "different")]),
        ]
        sub = compute_pairwise_rho(results)
        assert sub.passed is False
        assert "L1,L2" in sub.collapsed_pairs
        assert sub.pairwise_rho["L1,L2"] == 1.0

    def test_rho_just_above_threshold_collapses(self):
        """Rho strictly above the 0.25 threshold collapses (the just-over case)."""
        # L1={(1,a),(2,b)}, L2={(1,a),(3,c)}: intersection=1, union=3 -> rho=0.333... > 0.25.
        results = [
            self._make_result("L1", [("f.py", 1, "a"), ("f.py", 2, "b")]),
            self._make_result("L2", [("f.py", 1, "a"), ("f.py", 3, "c")]),
            self._make_result("L3", [("f.py", 99, "z")]),
        ]
        sub = compute_pairwise_rho(results)
        assert sub.pairwise_rho["L1,L2"] == pytest.approx(1 / 3)
        assert sub.passed is False

    def test_rho_exactly_at_threshold_passes(self):
        """TEST-A-005: rho == EXACTLY 0.25 PASSES (the bound is `>`, not `>=`).

        L1={(1,a),(2,b)}, L2={(1,a),(3,c),(4,d)}: intersection={(1,a)}=1, union=4 -> rho=0.25
        exactly (1/4 is exact in IEEE-754). 0.25 > 0.25 is False, so the pair does NOT collapse.
        A `>=` regression would flip this to a false LENS_COLLAPSE — this guards the boundary.
        """
        results = [
            self._make_result("L1", [("f.py", 1, "a"), ("f.py", 2, "b")]),
            self._make_result("L2", [("f.py", 1, "a"), ("f.py", 3, "c"), ("f.py", 4, "d")]),
            self._make_result("L3", [("f.py", 99, "z")]),
        ]
        sub = compute_pairwise_rho(results)
        assert sub.pairwise_rho["L1,L2"] == 0.25  # exact, not approx
        assert sub.passed is True
        assert "L1,L2" not in sub.collapsed_pairs

    def test_custom_thresholds(self):
        """Per-pair threshold overrides work."""
        findings_a = [("f.py", 1, "a")]
        findings_b = [("f.py", 1, "a"), ("f.py", 2, "b")]
        results = [
            self._make_result("L1", findings_a),
            self._make_result("L2", findings_b),
            self._make_result("L3", [("other.py", 99, "z")]),
        ]
        # Without override: rho = 1/2 = 0.5 > 0.25 -> collapse
        sub_default = compute_pairwise_rho(results)
        assert sub_default.passed is False

        # With override allowing higher rho for L1,L2
        sub_custom = compute_pairwise_rho(results, thresholds={"L1,L2": 0.6})
        assert sub_custom.passed is True

    def test_single_lens_always_passes(self):
        """Can't compute pairwise rho with < 2 lenses."""
        results = [self._make_result("L1", [("f.py", 1, "a")])]
        sub = compute_pairwise_rho(results)
        assert sub.passed is True
        assert sub.pairwise_rho == {}

    def test_empty_findings_independent(self):
        """Lenses with no findings should show rho=0."""
        results = [
            self._make_result("L1", []),
            self._make_result("L2", []),
            self._make_result("L3", []),
        ]
        sub = compute_pairwise_rho(results)
        assert sub.passed is True
        assert all(v == 0.0 for v in sub.pairwise_rho.values())
