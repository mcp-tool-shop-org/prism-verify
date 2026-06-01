"""Tests for verdict aggregation (engine.aggregate_verdict).

Pins the conservative ordering and the two audit-surfaced bugs: a FAIL with only
minor/empty findings must not become ACCEPT, and a mixed PASS+UNCERTAIN must ESCALATE
rather than silently ACCEPT.
"""

from __future__ import annotations

from prism.core.engine import aggregate_verdict
from prism.core.types import Finding, LensOutcome, LensResult, Verdict


def _lr(outcome: LensOutcome, *, findings=None, confidence: float = 0.9) -> LensResult:
    return LensResult(
        lens="x",
        model_family="google",
        model_id="g",
        outcome=outcome,
        findings=findings or [],
        confidence=confidence,
    )


def _fail(severity: str) -> LensResult:
    return _lr(LensOutcome.FAIL, findings=[Finding(category="c", evidence="e", severity=severity)])


class TestAggregateVerdict:
    def test_all_pass_is_accept(self) -> None:
        verdict, _, _ = aggregate_verdict([_lr(LensOutcome.PASS)] * 3)
        assert verdict == Verdict.ACCEPT

    def test_pass_plus_uncertain_escalates_not_accepts(self) -> None:
        # Headline bug: mixed PASS + UNCERTAIN previously collapsed to ACCEPT.
        results = [_lr(LensOutcome.PASS), _lr(LensOutcome.PASS), _lr(LensOutcome.UNCERTAIN)]
        verdict, _, _ = aggregate_verdict(results)
        assert verdict == Verdict.ESCALATE

    def test_all_uncertain_escalates(self) -> None:
        verdict, _, _ = aggregate_verdict([_lr(LensOutcome.UNCERTAIN)] * 3)
        assert verdict == Verdict.ESCALATE

    def test_fail_with_minor_finding_is_revise_not_accept(self) -> None:
        # Audit bug: a FAIL whose findings are all minor used to fall through to ACCEPT.
        results = [_lr(LensOutcome.PASS), _lr(LensOutcome.PASS), _fail("minor")]
        verdict, _, retryable = aggregate_verdict(results)
        assert verdict == Verdict.REVISE
        assert retryable is True

    def test_fail_with_no_findings_is_revise(self) -> None:
        verdict, _, _ = aggregate_verdict([_lr(LensOutcome.PASS), _lr(LensOutcome.FAIL)])
        assert verdict == Verdict.REVISE

    def test_fail_with_critical_is_refuse(self) -> None:
        verdict, _, retryable = aggregate_verdict([_lr(LensOutcome.PASS), _fail("critical")])
        assert verdict == Verdict.REFUSE
        assert retryable is False

    def test_fail_major_is_revise(self) -> None:
        verdict, _, _ = aggregate_verdict([_fail("major"), _lr(LensOutcome.PASS)])
        assert verdict == Verdict.REVISE

    def test_fail_precedes_uncertain(self) -> None:
        # A concrete FAIL is more actionable than uncertainty.
        verdict, _, _ = aggregate_verdict([_fail("major"), _lr(LensOutcome.UNCERTAIN)])
        assert verdict == Verdict.REVISE

    def test_confidence_is_minimum(self) -> None:
        results = [_lr(LensOutcome.PASS, confidence=0.9), _lr(LensOutcome.PASS, confidence=0.4)]
        _, confidence, _ = aggregate_verdict(results)
        assert confidence == 0.4
