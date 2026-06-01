"""Tests for verifier-response parsing robustness (parse_lens_response).

A verifier model's response must never crash verify(): malformed JSON, markdown
fences, out-of-enum severities/outcomes, and out-of-range confidences all have to
degrade gracefully. These tests pin that contract.
"""

from __future__ import annotations

from prism.core.types import LensOutcome, LensResult
from prism.lenses.base import parse_lens_response


def _parse(content: str) -> LensResult:
    return parse_lens_response(
        content, lens="test_lens", model_family="google", model_id="gemini-2.5-pro"
    )


class TestParseLensResponse:
    def test_clean_pass(self) -> None:
        r = _parse('{"outcome": "pass", "confidence": 0.9, "findings": []}')
        assert r.outcome == LensOutcome.PASS
        assert r.confidence == 0.9
        assert r.findings == []
        assert r.errored is False

    def test_markdown_fenced_json(self) -> None:
        content = (
            '```json\n{"outcome": "fail", "confidence": 0.8, '
            '"findings": [{"category": "x", "evidence": "y", "severity": "major"}]}\n```'
        )
        r = _parse(content)
        assert r.outcome == LensOutcome.FAIL
        assert r.errored is False
        assert len(r.findings) == 1

    def test_prose_prefixed_json(self) -> None:
        content = 'Here is my analysis:\n{"outcome": "pass", "confidence": 0.7, "findings": []}'
        r = _parse(content)
        assert r.outcome == LensOutcome.PASS
        assert r.errored is False

    def test_out_of_enum_severity_is_coerced_not_crashed(self) -> None:
        # 'high' is one of the most common LLM severity drifts; must not raise.
        content = (
            '{"outcome": "fail", "confidence": 0.6, '
            '"findings": [{"category": "bug", "evidence": "z", "severity": "high"}]}'
        )
        r = _parse(content)
        assert r.outcome == LensOutcome.FAIL
        assert r.findings[0].severity == "major"  # 'high' -> 'major'
        assert r.errored is False

    def test_low_severity_coerced_to_minor(self) -> None:
        content = (
            '{"outcome": "fail", "confidence": 0.6, '
            '"findings": [{"category": "b", "evidence": "z", "severity": "low"}]}'
        )
        r = _parse(content)
        assert r.findings[0].severity == "minor"

    def test_out_of_enum_outcome_degrades_to_errored_uncertain(self) -> None:
        # A model emitting verdict vocab ('accept') instead of outcome vocab must
        # not crash and must NOT be trusted as PASS — it degrades to errored UNCERTAIN.
        r = _parse('{"outcome": "accept", "confidence": 0.9, "findings": []}')
        assert r.outcome == LensOutcome.UNCERTAIN
        assert r.errored is True

    def test_confidence_out_of_range_clamped(self) -> None:
        assert _parse('{"outcome": "pass", "confidence": 1.5, "findings": []}').confidence == 1.0
        assert _parse('{"outcome": "pass", "confidence": -0.2, "findings": []}').confidence == 0.0

    def test_non_numeric_confidence_defaults(self) -> None:
        r = _parse('{"outcome": "pass", "confidence": "high", "findings": []}')
        assert r.confidence == 0.5

    def test_not_json_is_errored_uncertain(self) -> None:
        r = _parse("the model just wrote prose with no JSON object at all")
        assert r.outcome == LensOutcome.UNCERTAIN
        assert r.errored is True
        assert r.findings[0].category == "parse_error"

    def test_non_object_json_is_errored(self) -> None:
        r = _parse("[1, 2, 3]")
        assert r.errored is True
        assert r.outcome == LensOutcome.UNCERTAIN

    def test_missing_outcome_is_errored(self) -> None:
        r = _parse('{"confidence": 0.9, "findings": []}')
        assert r.outcome == LensOutcome.UNCERTAIN
        assert r.errored is True

    def test_findings_with_non_dict_entries_skipped(self) -> None:
        content = (
            '{"outcome": "fail", "confidence": 0.5, '
            '"findings": ["not a dict", {"category": "c", "evidence": "e", "severity": "minor"}]}'
        )
        r = _parse(content)
        assert len(r.findings) == 1
        assert r.findings[0].severity == "minor"

    def test_string_line_number_coerced(self) -> None:
        content = (
            '{"outcome": "fail", "confidence": 0.5, "findings": '
            '[{"category": "c", "evidence": "e", "severity": "minor", '
            '"line": "42", "file": "x.py"}]}'
        )
        r = _parse(content)
        assert r.findings[0].line == 42
        assert r.findings[0].file == "x.py"
