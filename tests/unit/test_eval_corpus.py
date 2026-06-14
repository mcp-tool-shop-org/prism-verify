"""Corpus integrity tests — labels present, splits disjoint (no leakage), build/load round-trips."""

from __future__ import annotations

from dataclasses import replace

from prism.eval.corpus import (
    CORPUS_CLASSES,
    SPLITS,
    Sample,
    build_corpus,
    check_corpus_integrity,
    corpus_content_hash,
    generate_samples,
    load_corpus,
)

_VALID_TYPES = {"code", "tool_call", "citations"}
_VALID_VERDICTS = {"accept", "revise", "refuse", "escalate"}
_TARGET_LENSES = {
    "contract_completeness",
    "invariant",
    "groundedness",
    "cross_boundary",
    "citation",
}


def _all() -> list[Sample]:
    return [s for sp in SPLITS for s in generate_samples(sp)]


class TestCorpusStructure:
    def test_every_sample_is_well_formed(self) -> None:
        for s in _all():
            assert s.artifact_type in _VALID_TYPES
            assert s.expected_verdict in _VALID_VERDICTS
            assert s.target_lens in _TARGET_LENSES
            assert s.content and s.intent  # non-empty
            assert isinstance(s.positive, bool)

    def test_each_target_lens_has_positives_and_negatives(self) -> None:
        from collections import Counter

        pos: Counter[str] = Counter()
        neg: Counter[str] = Counter()
        for s in _all():
            (pos if s.positive else neg)[s.target_lens] += 1
        for lens in _TARGET_LENSES:
            assert pos[lens] >= 3, f"{lens} has too few positives: {pos[lens]}"
            assert neg[lens] >= 1, f"{lens} has no negative/clean counterpart"

    def test_positive_means_defect_clean_means_accept(self) -> None:
        for s in _all():
            if s.positive:
                assert s.expected_verdict in {"refuse", "revise", "escalate"}
                assert s.bug_class not in {"clean", "real"}
            else:
                assert s.expected_verdict == "accept"
                assert s.bug_class in {"clean", "real"}  # code/tool clean, or a real citation


class TestNoLeakage:
    def test_ids_are_split_disjoint(self) -> None:
        pub_ids = {s.id for s in generate_samples("public")}
        fresh_ids = {s.id for s in generate_samples("fresh")}
        assert pub_ids.isdisjoint(fresh_ids)

    def test_content_is_split_disjoint(self) -> None:
        # The fresh split must not reuse public content, or a 'fresh' measurement is contaminated.
        pub_content = {s.content for s in generate_samples("public")}
        fresh_content = {s.content for s in generate_samples("fresh")}
        assert pub_content.isdisjoint(fresh_content)

    def test_ids_unique_within_split(self) -> None:
        for sp in SPLITS:
            ids = [s.id for s in generate_samples(sp)]
            assert len(ids) == len(set(ids))


class TestBuildLoadRoundTrip:
    def test_build_then_load_matches_generate(self, tmp_path) -> None:
        manifest = build_corpus(tmp_path)
        assert manifest["schema"] == "prism-eval-corpus/v1"
        assert (tmp_path / "MANIFEST.json").exists()
        assert (tmp_path / "prevalence.json").exists()
        for cls in CORPUS_CLASSES:
            for sp in SPLITS:
                assert (tmp_path / cls / f"{sp}.jsonl").exists()
        loaded = {s.id: s for s in load_corpus(tmp_path, "all")}
        generated = {s.id: s for s in _all()}
        assert loaded == generated

    def test_load_split_filters(self, tmp_path) -> None:
        build_corpus(tmp_path)
        pub = load_corpus(tmp_path, "public")
        assert pub and all(s.split == "public" for s in pub)

    def test_sample_dict_round_trip(self) -> None:
        s = _all()[0]
        assert Sample.from_dict(s.to_dict()) == s

    def test_load_missing_corpus_raises(self, tmp_path) -> None:
        import pytest

        with pytest.raises(FileNotFoundError):
            load_corpus(tmp_path / "nope", "all")


class TestContentHash:
    """EVS-B-001: a deterministic content hash makes corpus drift visible by construction.

    A count-preserving edit (same number of samples, different content/label) MUST flip the hash;
    a no-op (reordering the same samples) MUST NOT — so a published report's corpus-hash is a real
    fingerprint of the sample set, not of file layout or insertion order.
    """

    def test_hash_is_deterministic_and_order_independent(self) -> None:
        samples = _all()
        h1 = corpus_content_hash(samples)
        h2 = corpus_content_hash(list(reversed(samples)))  # reorder = NO content change
        assert h1 == h2
        assert isinstance(h1, str) and len(h1) == 64  # sha256 hex

    def test_count_preserving_content_edit_flips_hash(self) -> None:
        samples = _all()
        before = corpus_content_hash(samples)
        # Swap one sample's content for different content WITHOUT changing the sample count.
        edited = list(samples)
        edited[0] = replace(edited[0], content=edited[0].content + "\n# drifted\n")
        assert len(edited) == len(samples)  # count preserved
        after = corpus_content_hash(edited)
        assert after != before, "a count-preserving content edit must change the hash (drift)"

    def test_count_preserving_label_edit_flips_hash(self) -> None:
        # Relabeling a sample (positive flag flip) is a silent corpus change the hash must catch.
        samples = _all()
        before = corpus_content_hash(samples)
        edited = list(samples)
        edited[0] = replace(edited[0], positive=not edited[0].positive)
        after = corpus_content_hash(edited)
        assert after != before

    def test_manifest_embeds_content_hash(self, tmp_path) -> None:
        import json

        build_corpus(tmp_path)
        manifest = json.loads((tmp_path / "MANIFEST.json").read_text(encoding="utf-8"))
        assert manifest["content_hash"] == corpus_content_hash(_all())


class TestIntegrityGate:
    def test_clean_corpus_passes(self) -> None:
        assert check_corpus_integrity(generate_samples("public")) == []
        assert check_corpus_integrity(_all()) == []

    def test_detects_duplicate_ids(self) -> None:
        s = generate_samples("public")[0]
        assert any("duplicate" in p for p in check_corpus_integrity([s, s]))

    def test_detects_positive_expecting_accept(self) -> None:
        bad = Sample(
            id="x",
            artifact_type="code",
            content="c",
            intent="i",
            positive=True,
            target_lens="invariant",
            bug_class="off_by_one",
            expected_verdict="accept",  # a defect that expects accept is malformed
            split="public",
        )
        assert check_corpus_integrity([bad])  # non-empty problem list
