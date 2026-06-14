"""Unit tests for ``report.summarize`` aggregation — known-answer over hand-built EvalRuns.

These pin the EVL-A-001 invariant: records the engine could not adjudicate (a structural
``VerifyError`` → ``unavailable=True``) must NOT corrupt the published calibration numbers
(ECE / Brier / mean-confidence / modal verdict / verdict-accuracy). A provider outage during
``prism eval`` should be *disclosed and excluded*, never silently folded into the metrics as a
confidence-0.0 wrong answer.
"""

from __future__ import annotations

import math

from prism.eval.corpus import Sample
from prism.eval.metrics import brier_score, expected_calibration_error
from prism.eval.report import summarize
from prism.eval.runner import EvalRun, RunRecord


def _sample(sid: str, *, positive: bool, target_lens: str = "invariant") -> Sample:
    return Sample(
        id=sid,
        artifact_type="code",
        content="def f():\n    return 1\n",
        intent="return one",
        positive=positive,
        target_lens=target_lens,
        bug_class="off_by_one" if positive else "clean",
        expected_verdict="refuse" if positive else "accept",
        split="public",
    )


def _ok_record(sid: str, run_index: int, *, verdict: str, confidence: float) -> RunRecord:
    """A genuine, available adjudication (engine returned a real verdict)."""
    return RunRecord(
        sample_id=sid,
        run_index=run_index,
        verdict=verdict,
        confidence=confidence,
        errored=False,
        unavailable=False,
        per_lens={"invariant": "fail" if verdict != "accept" else "pass"},
        pairwise_rho={},
    )


def _unavailable_record(sid: str, run_index: int) -> RunRecord:
    """A structural VerifyError placeholder — no real verdict (verdict=reason, conf 0.0)."""
    return RunRecord(
        sample_id=sid,
        run_index=run_index,
        verdict="provider_unavailable",  # a RefusalReason value, NOT a real verdict
        confidence=0.0,
        errored=True,
        unavailable=True,
        per_lens={},
        pairwise_rho={},
    )


def _run(samples: list[Sample], records: list[RunRecord], n_runs: int) -> EvalRun:
    return EvalRun(
        records=records,
        samples={s.id: s for s in samples},
        n_runs=n_runs,
        verifier_label="ollama-known-answer",  # NOT mock/offline, so no mock note pollutes notes
        caller_family="anthropic",
    )


class TestReproducibilityProvenance:
    """EVS-B-001/002: the report must NAME which model(s) produced the numbers, at what temperature,
    with which seed, over which corpus content-hash — so a published artifact is reproducible by
    construction rather than asserted."""

    def test_report_carries_resolved_models_temperature_seed_and_corpus_hash(self) -> None:
        from prism.eval.report import render_json, render_markdown

        s = _sample("s1", positive=True)
        records = [_ok_record("s1", 0, verdict="refuse", confidence=0.8)]
        run = EvalRun(
            records=records,
            samples={s.id: s},
            n_runs=1,
            verifier_label="ollama",
            caller_family="anthropic",
            resolved_model_ids=["qwen3:14b", "mistral:7b"],
            effective_temperature=0.0,
            seed=1234,
            corpus_content_hash="deadbeef" * 8,
        )
        report = summarize(run)
        assert report.resolved_model_ids == ["mistral:7b", "qwen3:14b"]  # deduped + sorted
        assert math.isclose(report.effective_temperature, 0.0)
        assert report.seed == 1234
        assert report.corpus_content_hash == "deadbeef" * 8

        md = render_markdown(report)
        assert "qwen3:14b" in md and "mistral:7b" in md
        assert "temp" in md.lower()
        assert ("deadbeef" * 8)[:12] in md  # at least the short corpus-hash prefix is shown
        assert all(ord(c) < 128 for c in md)  # ASCII-safe
        import json as _json

        _json.loads(render_json(report))

    def test_report_handles_unrecorded_provenance_gracefully(self) -> None:
        """An EvalRun built without provenance (older callers / tests) renders without crashing."""
        from prism.eval.report import render_markdown

        s = _sample("s1", positive=True)
        run = _run([s], [_ok_record("s1", 0, verdict="refuse", confidence=0.8)], n_runs=1)
        report = summarize(run)
        assert report.resolved_model_ids == []
        assert report.effective_temperature is None
        assert report.seed is None
        # Markdown still renders an honest "not recorded" rather than crashing.
        md = render_markdown(report)
        assert all(ord(c) < 128 for c in md)


class TestPrevalenceCaveat:
    """EVS-B-003: precision is reported raw at the corpus's balanced ~50% prevalence. The report
    must SAY so (an explicit caveat), not let a reader mistake it for deployment precision."""

    def test_precision_prevalence_caveat_present_when_a_lens_has_precision(self) -> None:
        # A measured positive + clean pair gives the lens a precision number to caveat.
        bug = _sample("b", positive=True)
        clean = _sample("c", positive=False)
        records = [
            _ok_record("b", 0, verdict="refuse", confidence=0.8),
            _ok_record("c", 0, verdict="accept", confidence=0.8),
        ]
        report = summarize(_run([bug, clean], records, n_runs=1))
        assert any(
            "precision" in n.lower() and "prevalence" in n.lower() for n in report.notes
        ), f"missing prevalence caveat on precision: {report.notes}"


class TestUnavailableExcludedFromMetrics:
    def test_partial_unavailable_uses_genuine_records_only(self) -> None:
        """A positive sample: 2 genuine correct flags @0.9 + 1 unavailable placeholder.

        Known answer (genuine-only): modal verdict = 'refuse' (correct, since positive), mean
        confidence = 0.9, ECE/Brier computed at conf 0.9 with correct=True.

        WITHOUT the fix the unavailable record (verdict=reason, conf 0.0) is folded in: mean
        confidence drops to (0.9+0.9+0.0)/3 = 0.6 and — worse — for a single-sample run the modal
        verdict can tip and the calibration point shifts, inflating ECE. WITH the fix the metrics
        match the genuine-only computation exactly.
        """
        sample = _sample("s-bug", positive=True)
        records = [
            _ok_record("s-bug", 0, verdict="refuse", confidence=0.9),
            _ok_record("s-bug", 1, verdict="refuse", confidence=0.9),
            _unavailable_record("s-bug", 2),
        ]
        report = summarize(_run([sample], records, n_runs=3))

        # Genuine-only known answer: one sample, correct flag, confidence 0.9.
        expected_ece = expected_calibration_error([0.9], [True])
        expected_brier = brier_score([0.9], [True])

        assert math.isclose(report.ece, expected_ece), f"ECE corrupted: {report.ece}"
        assert math.isclose(report.brier, expected_brier), f"Brier corrupted: {report.brier}"
        # Verdict accuracy: the genuine modal verdict is 'refuse' on a positive => correct => 1.0.
        assert math.isclose(report.verdict_accuracy_overall, 1.0)
        # A disclosure note MUST be present (silent exclusion is as bad as silent inclusion).
        assert any("unavailable" in n.lower() and "excluded" in n.lower() for n in report.notes), (
            f"no disclosure note for excluded records: {report.notes}"
        )

    def test_all_unavailable_sample_dropped_not_counted_wrong(self) -> None:
        """A sample whose every record is unavailable has NO measurement.

        It must be excluded from verdict-accuracy/ECE/Brier entirely — not scored as wrong. Here a
        clean sample is fully measured (correct, conf 0.95) and a second sample is fully
        unavailable. The metrics must equal the single genuine sample's, NOT be halved by counting
        the unavailable sample as a 0.0-confidence wrong answer.
        """
        good = _sample("s-clean", positive=False)
        dead = _sample("s-dead", positive=True)
        records = [
            _ok_record("s-clean", 0, verdict="accept", confidence=0.95),
            _unavailable_record("s-dead", 0),
        ]
        report = summarize(_run([good, dead], records, n_runs=1))

        expected_ece = expected_calibration_error([0.95], [True])
        expected_brier = brier_score([0.95], [True])

        assert math.isclose(report.ece, expected_ece)
        assert math.isclose(report.brier, expected_brier)
        # Only the genuine clean sample is scored; it is correct => 1.0 (not 0.5 counting the dead).
        assert math.isclose(report.verdict_accuracy_overall, 1.0)
        assert any("unavailable" in n.lower() for n in report.notes)

    def test_no_unavailable_no_disclosure_note(self) -> None:
        """When nothing is excluded, no spurious unavailability note is emitted."""
        s = _sample("s1", positive=True)
        records = [_ok_record("s1", 0, verdict="refuse", confidence=0.8)]
        report = summarize(_run([s], records, n_runs=1))
        assert not any("unavailable" in n.lower() for n in report.notes)

    def test_errored_but_available_record_is_kept(self) -> None:
        """An ``errored`` record that still carries a real verdict+confidence is genuine: kept.

        A lens fault where the engine still returned a verdict is a real adjudication; only
        ``unavailable`` (structural VerifyError) drops out. Here both records are genuine (one
        flagged errored=True but available), so both confidences feed the mean.
        """
        s = _sample("s1", positive=True)
        records = [
            RunRecord(
                sample_id="s1",
                run_index=0,
                verdict="refuse",
                confidence=0.9,
                errored=True,  # a lens fault, but the engine still produced a verdict
                unavailable=False,
                per_lens={"invariant": "fail"},
                pairwise_rho={},
            ),
            _ok_record("s1", 1, verdict="refuse", confidence=0.7),
        ]
        report = summarize(_run([s], records, n_runs=2))
        # Mean confidence over BOTH genuine records: (0.9 + 0.7) / 2 = 0.8.
        expected_ece = expected_calibration_error([0.8], [True])
        assert math.isclose(report.ece, expected_ece)
