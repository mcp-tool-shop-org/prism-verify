"""Unit tests for calibration: rho-threshold sweep, family A/B, and the pairwise primitive."""

from __future__ import annotations

from prism.eval.calibrate import family_ab, pairwise_prefer, rho_threshold_sweep
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
        # family_ab reuses _accuracy(_sample_rows) — confirm the sibling migration covers it too.
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
        ab = family_ab(run, same)
        assert ab.family_different_accuracy == 1.0  # both genuine-correct
        assert ab.same_family_accuracy == 0.5  # s1 genuine-wrong, s2 correct (unavailable ignored)
        assert ab.delta == 0.5


class TestFamilyAB:
    def test_positive_delta_when_family_different_wins(self) -> None:
        diff = _run([("s1", True, "refuse", 0.1), ("s2", True, "refuse", 0.1)])  # both correct
        same = _run([("s1", True, "accept", 0.1), ("s2", True, "refuse", 0.1)])  # one wrong
        ab = family_ab(diff, same)
        assert ab.family_different_accuracy == 1.0
        assert ab.same_family_accuracy == 0.5
        assert ab.delta == 0.5


class TestPairwisePrefer:
    def test_better_verdict_wins(self) -> None:
        assert pairwise_prefer("accept", 0.9, "refuse", 0.9) == "a"
        assert pairwise_prefer("refuse", 0.9, "accept", 0.8) == "b"

    def test_verdict_tie_broken_by_confidence(self) -> None:
        assert pairwise_prefer("accept", 0.9, "accept", 0.8) == "a"

    def test_full_tie(self) -> None:
        assert pairwise_prefer("accept", 0.5, "accept", 0.5) == "tie"
