"""Tests for the offline QuixBugs ingester (``prism.eval.realbug.ingest_quixbugs``).

The ingester turns the vendored, MIT-licensed QuixBugs program pairs into corpus ``Sample``s in the
EXACT ``corpus.Sample`` shape (no schema change). Each program yields a buggy (positive) and a fixed
(negative) sample; the maps that label them (lens / intent / bug_class) are checked in, so these
tests pin: valid fields, the lens/verdict invariants, and that the result passes the ANDON gate.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from prism.eval.corpus import DEFAULT_QUIXBUGS_DIR, check_corpus_integrity
from prism.eval.realbug import (
    _QUIXBUGS_BUG_CLASS,
    _QUIXBUGS_INTENT,
    _QUIXBUGS_LENS_MAP,
    ingest_quixbugs,
)

# QuixBugs are plain functions: only the two CODE-applicable lenses apply (cross_boundary is the
# tool-call lens; groundedness is the fabricated-API/citation lens — neither fits an algorithm).
_CODE_LENSES = {"contract_completeness", "invariant"}
_VALID_VERDICTS = {"accept", "revise", "refuse", "escalate"}


@pytest.fixture
def samples():
    if not DEFAULT_QUIXBUGS_DIR.exists():  # pragma: no cover - vendored data must be present
        pytest.skip(f"vendored QuixBugs missing at {DEFAULT_QUIXBUGS_DIR}")
    return ingest_quixbugs(DEFAULT_QUIXBUGS_DIR, split="public")


class TestMapsAreConsistent:
    def test_every_mapped_program_has_all_three_labels(self) -> None:
        # A program must be in all three maps or it is silently skipped; keep them in lockstep.
        assert set(_QUIXBUGS_LENS_MAP) == set(_QUIXBUGS_INTENT) == set(_QUIXBUGS_BUG_CLASS)

    def test_lens_map_only_uses_code_lenses(self) -> None:
        assert set(_QUIXBUGS_LENS_MAP.values()) <= _CODE_LENSES

    def test_no_bug_class_collides_with_negative_reserved_labels(self) -> None:
        # 'clean'/'real' are reserved for negatives by check_corpus_integrity; positives differ.
        assert not ({"clean", "real"} & set(_QUIXBUGS_BUG_CLASS.values()))


class TestIngest:
    def test_yields_buggy_positive_and_fixed_negative_pairs(self, samples) -> None:
        assert samples
        assert len(samples) % 2 == 0
        by_id = {s.id: s for s in samples}
        # For every -buggy there is a matching -fixed (and vice versa).
        for s in samples:
            if s.id.endswith("-buggy"):
                assert s.positive is True
                mate = by_id.get(s.id.removesuffix("-buggy") + "-fixed")
                assert mate is not None and mate.positive is False
            elif s.id.endswith("-fixed"):
                assert s.positive is False
                assert by_id.get(s.id.removesuffix("-fixed") + "-buggy") is not None
            else:  # pragma: no cover - ids are always one of the two suffixes
                raise AssertionError(f"unexpected id suffix: {s.id}")

    def test_every_sample_is_well_formed(self, samples) -> None:
        for s in samples:
            assert s.id.startswith("quixbugs-")
            assert s.artifact_type == "code"
            assert s.content.strip() and s.intent.strip()
            assert s.target_lens in _CODE_LENSES
            assert s.expected_verdict in _VALID_VERDICTS
            assert s.split == "public"
            assert isinstance(s.positive, bool)

    def test_positive_buggy_never_expects_accept(self, samples) -> None:
        # The core ANDON invariant: a defect that "expects accept" is malformed (integrity-fails).
        for s in samples:
            if s.positive:
                assert s.expected_verdict in {"revise", "refuse"}
                assert s.expected_verdict != "accept"
                assert s.bug_class not in {"clean", "real"}

    def test_negative_fixed_expects_accept(self, samples) -> None:
        for s in samples:
            if not s.positive:
                assert s.expected_verdict == "accept"
                assert s.bug_class == "clean"

    def test_buggy_and_fixed_content_differ(self, samples) -> None:
        by_id = {s.id: s for s in samples}
        for s in samples:
            if s.id.endswith("-buggy"):
                fixed = by_id[s.id.removesuffix("-buggy") + "-fixed"]
                assert s.content != fixed.content, f"{s.id}: buggy == fixed source"

    def test_passes_andon_integrity_gate(self, samples) -> None:
        assert check_corpus_integrity(samples) == []

    def test_split_argument_is_respected(self) -> None:
        if not DEFAULT_QUIXBUGS_DIR.exists():  # pragma: no cover
            pytest.skip("vendored QuixBugs missing")
        fresh = ingest_quixbugs(DEFAULT_QUIXBUGS_DIR, split="fresh")
        assert fresh and all(s.split == "fresh" for s in fresh)

    def test_deterministic_order(self, samples) -> None:
        again = ingest_quixbugs(DEFAULT_QUIXBUGS_DIR, split="public")
        assert [s.id for s in samples] == [s.id for s in again]


class TestMissingDir:
    def test_empty_dir_yields_nothing(self, tmp_path: Path) -> None:
        # No python_programs/correct_python_programs subdirs => no pairs, no crash.
        assert ingest_quixbugs(tmp_path) == []
