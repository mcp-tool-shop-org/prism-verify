"""Unit tests for eval metrics — every assertion is a hand-computed known value.

These pin the closed-form correctness of the calibration benchmark's math, so a regression in a
metric (which would silently distort prism's measured precision/recall/diversity) fails the suite.
"""

from __future__ import annotations

import math

from prism.eval.metrics import (
    ast_node_similarity,
    brier_score,
    cohen_kappa,
    confusion_matrix,
    coverage_gain,
    expected_calibration_error,
    krippendorff_alpha,
    pabak,
    quality_metrics,
    wilson_interval,
)


class TestConfusionAndQuality:
    def test_confusion_counts(self) -> None:
        c = confusion_matrix([True, True, False, False], [True, False, True, False])
        assert (c.tp, c.fn, c.fp, c.tn) == (1, 1, 1, 1)
        assert c.n == 4

    def test_quality_balanced_mix_mcc_zero(self) -> None:
        q = quality_metrics([True, True, False, False], [True, False, True, False])
        assert math.isclose(q.precision, 0.5)
        assert math.isclose(q.recall, 0.5)
        assert math.isclose(q.specificity, 0.5)
        assert math.isclose(q.f1, 0.5)
        assert math.isclose(q.balanced_accuracy, 0.5)
        assert math.isclose(q.mcc, 0.0)  # no better than chance

    def test_quality_perfect(self) -> None:
        q = quality_metrics([True, True, False, False], [True, True, False, False])
        assert math.isclose(q.precision, 1.0)
        assert math.isclose(q.recall, 1.0)
        assert math.isclose(q.f1, 1.0)
        assert math.isclose(q.mcc, 1.0)

    def test_quality_rubber_stamp_has_mcc_zero_not_high_accuracy(self) -> None:
        # A lens that flags NOTHING on a defect-rare set scores high accuracy but MCC 0 — the exact
        # failure prism exposes. 1 buggy, 9 clean; predict all clean.
        y_true = [True] + [False] * 9
        y_pred = [False] * 10
        q = quality_metrics(y_true, y_pred)
        assert math.isclose(q.mcc, 0.0)
        assert math.isclose(q.recall, 0.0)


class TestAgreement:
    def test_cohen_kappa_identical_is_one(self) -> None:
        assert math.isclose(cohen_kappa(["y", "y", "n"], ["y", "y", "n"]), 1.0)

    def test_cohen_kappa_chance_is_zero(self) -> None:
        assert math.isclose(cohen_kappa(["y", "y", "n", "n"], ["y", "n", "y", "n"]), 0.0)

    def test_cohen_kappa_known_value(self) -> None:
        # a=[y,y,y,n,n] b=[y,y,n,n,n]: p_o=0.8, p_e=0.48 -> kappa=0.32/0.52
        k = cohen_kappa(["y", "y", "y", "n", "n"], ["y", "y", "n", "n", "n"])
        assert math.isclose(k, 0.32 / 0.52, rel_tol=1e-9)

    def test_pabak(self) -> None:
        assert math.isclose(pabak(0.8), 0.6)

    def test_krippendorff_perfect(self) -> None:
        assert krippendorff_alpha([["a", "a"], ["b", "b"]]) == 1.0

    def test_krippendorff_systematic_disagreement_is_negative(self) -> None:
        alpha = krippendorff_alpha([["a", "b"], ["a", "b"]])
        assert alpha is not None and alpha < 0.0

    def test_krippendorff_known_partial(self) -> None:
        # units [a,a],[a,b],[b,b]: Do=2, De=3.6 -> alpha = 1 - 2/3.6 = 0.4444...
        alpha = krippendorff_alpha([["a", "a"], ["a", "b"], ["b", "b"]])
        assert alpha is not None and math.isclose(alpha, 1 - 2 / 3.6, rel_tol=1e-9)

    def test_krippendorff_handles_missing(self) -> None:
        # ragged: a unit with an abstention still contributes its pairable values
        assert krippendorff_alpha([["a", "a", None], ["b", "b", "b"]]) == 1.0

    def test_krippendorff_no_pairable_data_is_none(self) -> None:
        assert krippendorff_alpha([["a", None], [None, None]]) is None


class TestCalibration:
    def test_ece_known(self) -> None:
        # both predictions at conf 0.9, one right one wrong -> acc 0.5, |0.5-0.9| = 0.4
        assert math.isclose(expected_calibration_error([0.9, 0.9], [True, False]), 0.4)

    def test_ece_perfectly_calibrated(self) -> None:
        # conf 1.0 and always correct -> 0 error
        assert math.isclose(expected_calibration_error([1.0, 1.0], [True, True]), 0.0)

    def test_brier_known(self) -> None:
        # ((0.9-1)^2 + (0.1-0)^2)/2 = 0.01
        assert math.isclose(brier_score([0.9, 0.1], [True, False]), 0.01)

    def test_brier_perfect(self) -> None:
        assert math.isclose(brier_score([1.0, 0.0], [True, False]), 0.0)


class TestCoverageGain:
    def test_union_beats_single_and_flags_redundant_lens(self) -> None:
        cg = coverage_gain(
            {"L1": {"s1", "s2"}, "L2": {"s2", "s3"}, "L3": {"s1"}}, total_positives=4
        )
        assert cg.union_size == 3
        assert cg.best_single_size == 2
        assert cg.gain == 1  # union (3) beats the best single (2)
        assert math.isclose(cg.union_recall, 0.75)
        # greedy: L1 adds 2, then L2 adds 1 (s3), then L3 adds 0 -> L3 is redundant
        assert cg.marginal_gains[-1][1] == 0

    def test_single_lens_no_gain(self) -> None:
        cg = coverage_gain({"only": {"s1", "s2"}}, total_positives=2)
        assert cg.gain == 0
        assert math.isclose(cg.union_recall, 1.0)

    def test_tie_break_is_deterministic_across_input_orderings(self) -> None:
        # EVS-B-004: best-single + greedy marginal order must NOT depend on dict insertion order.
        # Three lenses with EQUAL coverage (2 each) and a fully redundant fourth. Whatever input
        # ordering is fed, the published best_single_lens and the greedy marginal chain must be
        # identical — otherwise prism's "best/redundant lens" output is nondeterministic.
        caught = {
            "groundedness": {"a", "b"},
            "invariant": {"c", "d"},
            "contract_completeness": {"e", "f"},
            "cross_boundary": {"a"},  # fully redundant (subset of groundedness)
        }
        orderings = [
            list(caught.items()),
            list(reversed(list(caught.items()))),
            sorted(caught.items(), key=lambda kv: kv[0]),
            sorted(caught.items(), key=lambda kv: kv[0], reverse=True),
        ]
        results = [coverage_gain(dict(order), total_positives=6) for order in orderings]
        first = results[0]
        for cg in results[1:]:
            assert cg.best_single_lens == first.best_single_lens
            assert cg.marginal_gains == first.marginal_gains
            assert cg.best_single_size == first.best_single_size
            assert cg.gain == first.gain
        # On equal coverage, the deterministic tie-break is the alphabetically-first lens name.
        assert first.best_single_lens == "contract_completeness"
        # Greedy order: the three 2-coverage lenses come first in name order, then the redundant +0.
        names = [lens for lens, _ in first.marginal_gains]
        assert names == [
            "contract_completeness",
            "groundedness",
            "invariant",
            "cross_boundary",
        ]
        assert first.marginal_gains[-1] == ("cross_boundary", 0)


class TestAstSimilarity:
    def test_structurally_identical_despite_renames(self) -> None:
        assert ast_node_similarity("x = 1", "y = 2") == 1.0

    def test_structurally_different(self) -> None:
        sim = ast_node_similarity("x = 1", "def f():\n    return 1")
        assert sim is not None and sim < 1.0

    def test_unparseable_returns_none(self) -> None:
        assert ast_node_similarity("x =", "y = 2") is None


class TestWilson:
    def test_interval_brackets_point(self) -> None:
        lo, hi = wilson_interval(8, 10)
        assert 0.0 <= lo < 0.8 < hi <= 1.0

    def test_zero_total(self) -> None:
        assert wilson_interval(0, 0) == (0.0, 0.0)
