"""Unit tests for calibration: rho-threshold sweep, family A/B, and the pairwise primitive."""

from __future__ import annotations

from prism.core.types import ModelFamily
from prism.eval.calibrate import (
    _mcnemar_delta_ci,
    compute_family_ab,
    discover_families,
    pairwise_prefer,
    pick_ab_pair,
    rho_threshold_sweep,
)
from prism.eval.corpus import Sample
from prism.eval.runner import EvalRun, RunRecord


def _sample(sid: str, positive: bool) -> Sample:
    return Sample(
        id=sid,
        artifact_type="code",
        content="x = 1",
        intent="do x",
        positive=positive,
        target_lens="invariant",
        bug_class="off_by_one" if positive else "clean",
        expected_verdict="refuse" if positive else "accept",
        split="public",
    )


def _rec(sid: str, verdict: str, rho: float, *, unavailable: bool = False) -> RunRecord:
    return RunRecord(
        sample_id=sid,
        run_index=0,
        verdict=verdict,
        confidence=0.0 if unavailable else 0.8,
        errored=unavailable,
        unavailable=unavailable,
        per_lens={},
        pairwise_rho={} if unavailable else {"a,b": rho},
    )


def _run(specs: list[tuple[str, bool, str, float]]) -> EvalRun:
    samples = {sid: _sample(sid, pos) for sid, pos, _, _ in specs}
    records = [_rec(sid, verdict, rho) for sid, _, verdict, rho in specs]
    return EvalRun(
        records=records, samples=samples, n_runs=1, verifier_label="t", caller_family="anthropic"
    )


class TestRhoSweep:
    def test_prefers_low_cutoff_when_high_rho_is_wrong(self) -> None:
        # Low-rho verifications are correct; high-rho ones wrong -> gating low maximizes score.
        run = _run(
            [
                ("s1", True, "refuse", 0.1),
                ("s2", True, "refuse", 0.1),
                ("s3", True, "accept", 0.4),
                ("s4", True, "accept", 0.4),
            ]
        )
        sweep = rho_threshold_sweep(run)
        assert sweep.baseline_accuracy == 0.5
        assert sweep.best_cutoff is not None and sweep.best_cutoff <= 0.15
        assert "degenerate" not in sweep.note

    def test_degenerate_when_rho_constant(self) -> None:
        run = _run([("s1", True, "refuse", 0.0), ("s2", False, "accept", 0.0)])
        sweep = rho_threshold_sweep(run)
        assert "degenerate" in sweep.note
        assert sweep.baseline_accuracy == 1.0


class TestUnavailableExcluded:
    """EVL-A-001 sibling: calibrate must mirror report.summarize and exclude unavailable records
    (structural VerifyError, verdict=reason, confidence=0.0) from every accuracy/verdict math."""

    def _run_with_unavailable(self) -> EvalRun:
        # s1: two genuine CORRECT runs (positive sample, refuse) + one unavailable run.
        #     Genuine-only modal verdict = "refuse" -> correct. The unavailable run, if counted,
        #     pollutes the per-run grouping (it carries verdict=reason, confidence=0.0).
        # s2: a genuine correct positive sample (refuse).
        samples = {
            "s1": _sample("s1", positive=True),
            "s2": _sample("s2", positive=True),
        }
        records = [
            _rec("s1", "refuse", 0.1),  # the one genuine measurement: correct (positive->refuse)
            _rec("s1", "invalid_artifact", 0.0, unavailable=True),
            _rec("s1", "invalid_artifact", 0.0, unavailable=True),  # 2 unavailable would tip modal
            _rec("s2", "refuse", 0.2),
        ]
        return EvalRun(
            records=records,
            samples=samples,
            n_runs=1,
            verifier_label="t",
            caller_family="anthropic",
        )

    def test_all_unavailable_sample_is_skipped_not_scored_wrong(self) -> None:
        # A sample whose every record is unavailable must be DROPPED, not scored as wrong.
        samples = {"good": _sample("good", positive=True), "dead": _sample("dead", positive=True)}
        records = [
            _rec("good", "refuse", 0.1),  # genuine + correct
            _rec("dead", "invalid_artifact", 0.0, unavailable=True),  # no measurement at all
        ]
        run = EvalRun(
            records=records,
            samples=samples,
            n_runs=1,
            verifier_label="t",
            caller_family="anthropic",
        )
        sweep = rho_threshold_sweep(run)
        # genuine-only: 1 sample, correct -> 1.0. Counting "dead" as wrong would give 0.5.
        assert sweep.baseline_accuracy == 1.0

    def test_baseline_accuracy_matches_genuine_only(self) -> None:
        run = self._run_with_unavailable()
        sweep = rho_threshold_sweep(run)
        # Both samples are correct on their genuine records -> 1.0. If the unavailable run on s1
        # were counted (verdict=invalid_artifact, neither refuse nor accept), s1's modal verdict
        # could tip and accuracy would drop below 1.0.
        assert sweep.baseline_accuracy == 1.0

    def test_family_ab_accuracy_matches_genuine_only(self) -> None:
        # compute_family_ab reuses _correct_by_sample (the unavailable-exclusion rule) — confirm
        # the pairing drops unavailable records on both arms.
        run = self._run_with_unavailable()
        # control run: same samples but s1's genuine modal verdict is wrong (accept on a positive).
        same = EvalRun(
            records=[
                _rec("s1", "accept", 0.1),
                _rec("s1", "invalid_artifact", 0.0, unavailable=True),
                _rec("s2", "refuse", 0.2),
            ],
            samples={"s1": _sample("s1", positive=True), "s2": _sample("s2", positive=True)},
            n_runs=1,
            verifier_label="t",
            caller_family="anthropic",
        )
        ab = compute_family_ab(run, same)
        assert ab.n_paired == 2  # both samples measured on BOTH arms (unavailable runs dropped)
        assert ab.family_different_accuracy == 1.0  # both genuine-correct
        assert ab.same_family_accuracy == 0.5  # s1 genuine-wrong, s2 correct (unavailable ignored)
        assert ab.delta == 0.5
        assert ab.family_different_correct == 2
        assert ab.same_family_correct == 1


class TestFamilyAB:
    def test_positive_delta_when_family_different_wins(self) -> None:
        diff = _run([("s1", True, "refuse", 0.1), ("s2", True, "refuse", 0.1)])  # both correct
        same = _run([("s1", True, "accept", 0.1), ("s2", True, "refuse", 0.1)])  # one wrong
        ab = compute_family_ab(diff, same)
        assert ab.n_paired == 2
        assert ab.family_different_accuracy == 1.0
        assert ab.same_family_accuracy == 0.5
        assert ab.delta == 0.5

    def test_paired_mcnemar_known_answer(self) -> None:
        """Hand-computed paired delta + Wald CI on a 4-sample fixture.

        T vs C correctness per sample (positive samples -> refuse=correct, accept=wrong):
          s1: T correct,   C wrong    -> b (discordant, treatment-favoring)
          s2: T correct,   C wrong    -> b
          s3: T wrong,     C correct  -> c (discordant, control-favoring)
          s4: T correct,   C correct  -> concordant
        So n=4, b=2, c=1.
          delta = (b - c)/n = (2 - 1)/4 = 0.25
          fd_acc = 3/4 = 0.75 ; sf_acc = 2/4 = 0.50 ; fd_acc - sf_acc = 0.25  (matches delta)
          Var = [(b+c) - (b-c)^2/n] / n^2 = [3 - 1/4] / 16 = 2.75/16 = 0.171875
          SE  = sqrt(0.171875) = 0.4145781...
          CI  = 0.25 +/- 1.96*SE = [-0.56257..., 1.06257...] -> hi clamped to 1.0
        """
        import math as _math
        treatment = _run(
            [
                ("s1", True, "refuse", 0.1),  # correct
                ("s2", True, "refuse", 0.1),  # correct
                ("s3", True, "accept", 0.1),  # wrong
                ("s4", True, "refuse", 0.1),  # correct
            ]
        )
        control = _run(
            [
                ("s1", True, "accept", 0.1),  # wrong
                ("s2", True, "accept", 0.1),  # wrong
                ("s3", True, "refuse", 0.1),  # correct
                ("s4", True, "refuse", 0.1),  # correct
            ]
        )
        ab = compute_family_ab(treatment, control)
        assert ab.n_paired == 4
        assert ab.family_different_correct == 3
        assert ab.same_family_correct == 2
        assert ab.family_different_accuracy == 0.75
        assert ab.same_family_accuracy == 0.50
        assert ab.delta == 0.25
        lo, hi = ab.delta_ci
        expected_se = _math.sqrt(((2 + 1) - (2 - 1) ** 2 / 4) / 16)  # sqrt(2.75/16)
        assert abs(lo - (0.25 - 1.96 * expected_se)) < 1e-9
        assert hi == 1.0  # upper bound clamped to 1.0

    def test_pairing_excludes_samples_not_measured_on_both_arms(self) -> None:
        """Only the intersection of measured samples is paired; one-arm-only samples are dropped."""
        treatment = _run([("s1", True, "refuse", 0.1), ("s2", True, "refuse", 0.1)])
        # control measured only s1 (s2 never appears) -> intersection is {s1}.
        control = _run([("s1", True, "refuse", 0.1)])
        ab = compute_family_ab(treatment, control)
        assert ab.n_paired == 1

    def test_all_unavailable_control_yields_n_paired_zero(self) -> None:
        """Control arm produced no genuine verdict anywhere -> empty intersection -> n_paired==0."""
        treatment = _run([("s1", True, "refuse", 0.1), ("s2", True, "refuse", 0.1)])
        control = EvalRun(
            records=[
                _rec("s1", "verifier_unavailable", 0.0, unavailable=True),
                _rec("s2", "verifier_unavailable", 0.0, unavailable=True),
            ],
            samples={"s1": _sample("s1", positive=True), "s2": _sample("s2", positive=True)},
            n_runs=1,
            verifier_label="same-family-control",
            caller_family="anthropic",
        )
        ab = compute_family_ab(treatment, control)
        assert ab.n_paired == 0
        assert ab.delta == 0.0
        assert ab.delta_ci == (0.0, 0.0)


class TestMcnemarCi:
    def test_no_discordant_pairs_collapses_interval(self) -> None:
        # b=c=0 over n concordant pairs: delta 0, variance 0 -> [0, 0].
        assert _mcnemar_delta_ci(0, 0, 5) == (0.0, 0.0)

    def test_symmetric_discordant_gives_zero_centered_interval(self) -> None:
        lo, hi = _mcnemar_delta_ci(2, 2, 8)  # delta 0, but nonzero spread
        assert lo < 0.0 < hi
        assert abs(lo + hi) < 1e-9  # symmetric about 0


class TestDiscovery:
    def test_pick_ab_pair_first_cross_family_in_routing_order(self) -> None:
        # anthropic routing order is GOOGLE, OPENAI, LOCAL. Only OPENAI + LOCAL available ->
        # treatment is OPENAI (the first cross-family in routing order that is configured).
        pair = pick_ab_pair(
            ModelFamily.ANTHROPIC, {ModelFamily.ANTHROPIC, ModelFamily.OPENAI, ModelFamily.LOCAL}
        )
        assert pair.ok
        assert pair.treatment == ModelFamily.OPENAI
        assert pair.control == ModelFamily.ANTHROPIC

    def test_pick_ab_pair_no_caller_provider_skips_with_reason(self) -> None:
        pair = pick_ab_pair(ModelFamily.ANTHROPIC, {ModelFamily.OPENAI})
        assert not pair.ok
        assert pair.reason is not None and "caller family" in pair.reason

    def test_pick_ab_pair_no_cross_family_skips_with_reason(self) -> None:
        pair = pick_ab_pair(ModelFamily.ANTHROPIC, {ModelFamily.ANTHROPIC})
        assert not pair.ok
        assert pair.reason is not None and "cross-family" in pair.reason

    def test_discover_families_from_providers(self) -> None:
        from prism.eval.runner import MockProvider

        providers = {
            "local": MockProvider(family=ModelFamily.LOCAL),
            "anthropic": MockProvider(family=ModelFamily.ANTHROPIC),
        }
        assert discover_families(providers) == {ModelFamily.LOCAL, ModelFamily.ANTHROPIC}


class TestPairwisePrefer:
    def test_better_verdict_wins(self) -> None:
        assert pairwise_prefer("accept", 0.9, "refuse", 0.9) == "a"
        assert pairwise_prefer("refuse", 0.9, "accept", 0.8) == "b"

    def test_verdict_tie_broken_by_confidence(self) -> None:
        assert pairwise_prefer("accept", 0.9, "accept", 0.8) == "a"

    def test_full_tie(self) -> None:
        assert pairwise_prefer("accept", 0.5, "accept", 0.5) == "tie"
