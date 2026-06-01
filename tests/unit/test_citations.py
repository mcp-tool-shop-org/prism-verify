"""Unit tests for the pure citation helpers (parsing, numeric guard, groundedness parse)."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from prism.core.citations import (
    numeric_mismatch,
    parse_citation_groundedness,
    parse_citations,
)


class TestParseCitations:
    def test_parses_array(self):
        content = json.dumps(
            [
                {"claim": "X improves Y", "identifier": "arXiv:2402.01817", "title": "T"},
                {"claim": "Z holds", "identifier": "10.1/x"},
            ]
        )
        cits = parse_citations(content)
        assert len(cits) == 2
        assert cits[0].identifier == "arXiv:2402.01817"

    def test_rejects_non_array(self):
        with pytest.raises(ValueError):
            parse_citations('{"claim": "x"}')

    def test_rejects_non_object_element(self):
        with pytest.raises(ValueError):
            parse_citations('["just a string"]')

    def test_rejects_missing_claim(self):
        # claim is required (min_length=1) -> pydantic ValidationError
        with pytest.raises(ValidationError):
            parse_citations('[{"identifier": "arXiv:2402.01817"}]')


class TestNumericMismatch:
    def test_flags_percentage_swap(self):
        flagged, detail = numeric_mismatch("reports 95.8% accuracy", "we achieve 89% accuracy")
        assert flagged is True
        assert "95.8" in detail and "89" in detail

    def test_corroborated_percentage_passes(self):
        flagged, _ = numeric_mismatch("reports 89% accuracy", "we achieve 89.2% on the task")
        assert flagged is False  # 89 vs 89.2 is within the 0.5 tolerance

    def test_source_without_percentage_abstains(self):
        # The numeric guard must NOT false-flag when the source simply omits the figure.
        flagged, _ = numeric_mismatch("reports 95.8% accuracy", "a method for doing the thing")
        assert flagged is False

    def test_claim_without_percentage_abstains(self):
        flagged, _ = numeric_mismatch("a qualitative claim", "we achieve 89%")
        assert flagged is False


class TestGroundednessParse:
    def test_parses_supported(self):
        out, span, conf = parse_citation_groundedness(
            '{"outcome": "supported", "confidence": 0.9, "supporting_span": "the abstract says X"}'
        )
        assert out == "supported"
        assert span == "the abstract says X"
        assert conf == 0.9

    def test_garbage_degrades_to_not_addressed(self):
        out, span, conf = parse_citation_groundedness("not json at all")
        assert out == "not_addressed"
        assert span is None
        assert conf == 0.0

    def test_out_of_enum_degrades(self):
        out, _, _ = parse_citation_groundedness('{"outcome": "accept"}')
        assert out == "not_addressed"

    def test_handles_fenced_json(self):
        out, _, _ = parse_citation_groundedness('```json\n{"outcome": "contradicted"}\n```')
        assert out == "contradicted"
