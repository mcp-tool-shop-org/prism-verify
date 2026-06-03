"""Unit tests for the pure citation helpers (parsing, numeric guard, groundedness parse)."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from prism.core.citations import (
    numeric_mismatch,
    numeric_unit_mismatch,
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


class TestNumericUnitMismatch:
    def test_flags_unit_scale_slip(self):
        # same number, same base unit, different metric prefix (milli vs micro) -> a contradiction
        flagged, detail = numeric_unit_mismatch(
            "the ring diameter was 42 milliarcseconds",
            "we measure an emission ring with a diameter of 42 micro-arcseconds",
        )
        assert flagged is True
        assert "arcsec" in detail

    def test_flags_comparison_direction_falsehood(self):
        flagged, detail = numeric_unit_mismatch(
            "the observed local significance exceeded the expected significance",
            "a local significance of 5.0 standard deviations; "
            "the expected significance is 5.8 standard deviations",
        )
        assert flagged is True
        assert "5.8" in detail

    def test_abstains_on_true_comparison(self):
        # observed 5.8 DID exceed expected 5.0 -> the claim is true -> must NOT flag
        flagged, _ = numeric_unit_mismatch(
            "the observed local significance exceeded the expected significance",
            "a local significance of 5.8 standard deviations; "
            "the expected significance is 5.0 standard deviations",
        )
        assert flagged is False

    def test_abstains_on_matching_units(self):
        flagged, _ = numeric_unit_mismatch(
            "the ring diameter was 42 microarcseconds", "a diameter of 42 micro-arcseconds"
        )
        assert flagged is False

    def test_abstains_without_units_or_comparison(self):
        flagged, _ = numeric_unit_mismatch(
            "a qualitative claim about the method", "we propose a new approach"
        )
        assert flagged is False

    def test_abstains_when_operands_unbindable(self):
        # 'fewer than two-thirds' has no second explicit source number to bind -> abstain
        flagged, _ = numeric_unit_mismatch(
            "the system found evidence for fewer than two-thirds of the claims",
            "we identify plausible evidence for 23 / 36 claims",
        )
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
