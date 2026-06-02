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


def _rec(sid: str, verdict: str, rho: float) -> RunRecord:
    return RunRecord(
        sample_id=sid,
        run_index=0,
        verdict=verdict,
        confidence=0.8,
        errored=False,
        unavailable=False,
        per_lens={},
        pairwise_rho={"a,b": rho},
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
