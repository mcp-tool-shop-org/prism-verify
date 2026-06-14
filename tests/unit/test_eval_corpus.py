"""Corpus integrity tests — labels present, splits disjoint (no leakage), build/load round-trips."""

from __future__ import annotations

from dataclasses import replace

from prism.eval.corpus import (
    CORPUS_CLASSES,
    DEFAULT_QUIXBUGS_DIR,
    SPLITS,
    Sample,
    build_corpus,
    check_corpus_integrity,
    corpus_content_hash,
    generate_samples,
    is_contaminated,
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
        # quixbugs_dir=None builds the AUTHORED-only corpus, which must round-trip generate_samples.
        manifest = build_corpus(tmp_path, quixbugs_dir=None)
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
        build_corpus(tmp_path, quixbugs_dir=None)
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

        # Authored-only build: the manifest hash must equal the hash of the authored sample set.
        build_corpus(tmp_path, quixbugs_dir=None)
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


class TestQuixBugsWiring:
    """F-01 v1.1: QuixBugs real-bug pairs land in the public split, contamination-flagged, and the
    ANDON gate still passes on the enlarged corpus."""

    def _skip_if_missing(self) -> None:
        if not DEFAULT_QUIXBUGS_DIR.exists():  # pragma: no cover - vendored data must be present
            import pytest

            pytest.skip(f"vendored QuixBugs missing at {DEFAULT_QUIXBUGS_DIR}")

    def test_build_includes_quixbugs_in_public_only(self, tmp_path) -> None:
        self._skip_if_missing()
        build_corpus(tmp_path)  # default => ingests vendored QuixBugs
        pub = load_corpus(tmp_path, "public")
        fresh = load_corpus(tmp_path, "fresh")
        quix_pub = [s for s in pub if is_contaminated(s.id)]
        assert quix_pub, "QuixBugs samples missing from public split"
        assert all(s.split == "public" for s in quix_pub)
        # The 'fresh' split must NOT be touched (it is the honest, uncontaminated signal).
        assert not any(is_contaminated(s.id) for s in fresh)

    def test_manifest_records_contamination_metadata(self, tmp_path) -> None:
        self._skip_if_missing()
        import json

        manifest = build_corpus(tmp_path)
        manifest_disk = json.loads((tmp_path / "MANIFEST.json").read_text(encoding="utf-8"))
        assert manifest == manifest_disk  # returned == written
        sources = manifest["sources"]
        assert sources["authored"]["contaminated"] is False
        quix = sources["quixbugs"]
        assert quix["contaminated"] is True
        assert quix["splits"] == ["public"]
        assert quix["license"] == "MIT"
        assert quix["n_samples"] > 0 and quix["n_program_pairs"] == quix["n_samples"] // 2
        assert manifest["contaminated_splits"] == ["public"]

    def test_quixbugs_build_hash_differs_from_authored_only(self, tmp_path) -> None:
        self._skip_if_missing()
        with_quix = build_corpus(tmp_path / "a")["content_hash"]
        without = build_corpus(tmp_path / "b", quixbugs_dir=None)["content_hash"]
        assert with_quix != without, "adding QuixBugs must change the corpus content hash"

    def test_andon_gate_passes_on_enlarged_corpus(self, tmp_path) -> None:
        self._skip_if_missing()
        build_corpus(tmp_path)
        loaded = load_corpus(tmp_path, "all")
        assert check_corpus_integrity(loaded) == []

    def test_positives_per_lens_rises_but_below_stability_bar(self, tmp_path) -> None:
        self._skip_if_missing()
        with_quix = build_corpus(tmp_path / "a")["positives_per_lens"]
        without = build_corpus(tmp_path / "b", quixbugs_dir=None)["positives_per_lens"]
        # QuixBugs only adds CODE positives (invariant + contract_completeness); they must rise.
        assert with_quix["invariant"] > without["invariant"]
        assert with_quix["contract_completeness"] > without["contract_completeness"]
        # Honest: still below the >=100/lens stability bar even after the real-bug upgrade.
        assert max(with_quix.values()) < 100

    def test_authored_only_build_has_no_contamination(self, tmp_path) -> None:
        manifest = build_corpus(tmp_path, quixbugs_dir=None)
        assert manifest["contaminated_splits"] == []
        assert manifest["sources"]["quixbugs"]["splits"] == []
        assert not any(is_contaminated(s.id) for s in load_corpus(tmp_path, "all"))
