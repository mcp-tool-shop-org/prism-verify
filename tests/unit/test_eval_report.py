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


def _citation_sample(sid: str, *, positive: bool) -> Sample:
    """A citations-artifact sample targeting the 'citation' lens (the per-lens-table-only lens)."""
    return Sample(
        id=sid,
        artifact_type="citations",
        content='[{"identifier": "2402.01817", "claim": "x"}]',
        intent="verify each citation exists and the stated finding matches the source",
        positive=positive,
        target_lens="citation",
        bug_class="fabricated" if positive else "real",
        expected_verdict="refuse" if positive else "accept",
        split="public",
    )


def _citation_record(sid: str, run_index: int, *, verdict: str, confidence: float) -> RunRecord:
    """A genuine citation adjudication: the engine emits a 'citation' lens result (engine.py)."""
    return RunRecord(
        sample_id=sid,
        run_index=run_index,
        verdict=verdict,
        confidence=confidence,
        errored=False,
        unavailable=False,
        per_lens={"citation": "fail" if verdict != "accept" else "pass"},
        pairwise_rho={},
    )


def _full4_record(sid: str, run_index: int, *, verdict: str, confidence: float) -> RunRecord:
    """A code/tool adjudication with a decision on all four _LLM_LENSES (feeds diversity)."""
    fail = "fail" if verdict != "accept" else "pass"
    return RunRecord(
        sample_id=sid,
        run_index=run_index,
        verdict=verdict,
        confidence=confidence,
        errored=False,
        unavailable=False,
        per_lens={
            "contract_completeness": fail,
            "cross_boundary": fail,
            "invariant": fail,
            "groundedness": fail,
        },
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


class TestCitationPromotedToPerLensTable:
    """F-01 v1.1 / wedge fork: 'citation' is the LARGEST positive set but was invisible because the
    per-lens table looped over _LLM_LENSES (which omits it). Promote it to the per-lens QUALITY
    table ONLY — the diversity matrix / Krippendorff / coverage_gain still use the 4 _LLM_LENSES."""

    def test_per_lens_table_includes_a_citation_row(self) -> None:
        from prism.eval.report import render_markdown

        bug = _citation_sample("cit-bug", positive=True)
        clean = _citation_sample("cit-clean", positive=False)
        records = [
            _citation_record("cit-bug", 0, verdict="refuse", confidence=0.8),
            _citation_record("cit-clean", 0, verdict="accept", confidence=0.8),
        ]
        report = summarize(_run([bug, clean], records, n_runs=1))
        lenses = {lr.lens for lr in report.per_lens}
        assert "citation" in lenses, f"citation missing from per-lens table: {lenses}"
        # The citation lens scored a real positive (the buggy citation was flagged).
        cit = next(lr for lr in report.per_lens if lr.lens == "citation")
        assert cit.positives == 1
        # And it renders into the markdown table.
        md = render_markdown(report)
        assert "| citation |" in md

    def test_diversity_matrix_uses_only_the_four_llm_lenses(self) -> None:
        """A full-4-lens code sample + a citation sample: the diversity matrix must be built from
        the 4 _LLM_LENSES only — the citation sample (no 4-lens decision) must NOT enter it, and the
        pairwise-kappa keys must never mention 'citation'."""
        code = _sample("code-bug", positive=True, target_lens="invariant")
        cit = _citation_sample("cit-bug", positive=True)
        records = [
            _full4_record("code-bug", 0, verdict="refuse", confidence=0.8),
            _citation_record("cit-bug", 0, verdict="refuse", confidence=0.8),
        ]
        report = summarize(_run([code, cit], records, n_runs=1))
        # citation is in the quality table...
        assert "citation" in {lr.lens for lr in report.per_lens}
        # ...but NEVER in the diversity matrix (kappa pairs are only among the 4 LLM lenses).
        for pair in report.pairwise_kappa:
            assert "citation" not in pair, f"diversity matrix leaked citation: {pair}"
        # The Krippendorff units came from the single full-4-lens sample, so alpha is computable
        # without the citation sample polluting it.
        llm = {"contract_completeness", "cross_boundary", "invariant", "groundedness"}
        for pair in report.pairwise_kappa:
            a, b = pair.split(",")
            assert a in llm and b in llm


class TestContaminationCaveat:
    """F-01 v1.1 2D: when the corpus contains contaminated (QuixBugs/public) samples, the report
    must print a caveat that the public-split number is a CEILING (verifiers may have memorized) and
    the fresh split is the honest signal. Mirrors the existing prevalence-caveat note style."""

    def test_caveat_present_when_a_contaminated_sample_is_scored(self) -> None:
        from prism.eval.report import render_markdown

        # A 'quixbugs-' id marks a contaminated (known-public) sample.
        s = Sample(
            id="quixbugs-gcd-buggy",
            artifact_type="code",
            content="def gcd(a, b):\n    return gcd(a % b, b)\n",
            intent="Return the greatest common divisor of a and b.",
            positive=True,
            target_lens="invariant",
            bug_class="wrong_recursive_args",
            expected_verdict="revise",
            split="public",
        )
        records = [_ok_record("quixbugs-gcd-buggy", 0, verdict="revise", confidence=0.8)]
        report = summarize(_run([s], records, n_runs=1))
        assert report.contaminated_sample_count == 1
        assert any(
            "ceiling" in n.lower() and ("contaminat" in n.lower() or "memoriz" in n.lower())
            for n in report.notes
        ), f"missing contamination caveat: {report.notes}"
        md = render_markdown(report)
        assert "CEILING" in md

    def test_no_caveat_when_no_contaminated_samples(self) -> None:
        s = _sample("clean-authored", positive=True)
        records = [_ok_record("clean-authored", 0, verdict="refuse", confidence=0.8)]
        report = summarize(_run([s], records, n_runs=1))
        assert report.contaminated_sample_count == 0
        assert not any("ceiling" in n.lower() for n in report.notes)
