"""Unit tests for the CodeJudgeBench loader + harness (F-01 sub-build 3).

Offline + fixture-based: NO network, NO HF ``datasets`` lib (the default suite must pass without
the ``[bench]`` extra, like nli works torch-free). The harness runs against a DETERMINISTIC fake
engine so the chosen-vs-rejected reduction is exercised exactly.

The design's #1 risk is a pos/neg (chosen/rejected) SWAP inverting the entire accuracy number, so
the tests pin BOTH directions: an engine preferring the CHOSEN side -> accuracy 1.0; one preferring
the REJECTED side -> 0.0. Plus: ANDON column validation, tie-counted-wrong, position-consistency,
and that ``pairwise_prefer`` is actually exercised (it had zero callers before this build).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from prism.core.types import VerifyError, VerifyRequest
from prism.eval.benchmarks.codejudgebench import (
    DEFAULT_FIXTURE,
    CJBColumnError,
    CJBItem,
    cjb_content_hash,
    load_codejudgebench,
    load_codejudgebench_offline,
)
from prism.eval.benchmarks.harness import (
    run_codejudgebench,
    summarize_codejudgebench,
)

# --- a deterministic fake engine (the harness only reads .verdict.value + .confidence) ---


@dataclass
class _FakeVerdict:
    value: str


@dataclass
class _FakeResponse:
    verdict: _FakeVerdict
    confidence: float


class _PreferEngine:
    """Returns ``accept`` for whichever code substring it is told to favor, ``refuse`` otherwise.

    Verdict rank accept(3) > refuse(0), so pairwise_prefer picks the accepted side — letting a
    test drive prism's preference to either side deterministically (proves no chosen/rejected swap).
    """

    def __init__(self, accept_marker: str) -> None:
        self._accept_marker = accept_marker

    async def verify(self, request: VerifyRequest) -> _FakeResponse:
        content = request.artifact.content
        verdict = "accept" if self._accept_marker in content else "refuse"
        return _FakeResponse(_FakeVerdict(verdict), 0.9)


class _TieEngine:
    """Always returns the SAME verdict + SAME confidence -> pairwise_prefer returns 'tie'."""

    async def verify(self, request: VerifyRequest) -> _FakeResponse:
        return _FakeResponse(_FakeVerdict("accept"), 0.7)


class _UnavailableEngine:
    """Always returns a structural VerifyError -> the item is unavailable (EVL-A-001 parity)."""

    async def verify(self, request: VerifyRequest) -> VerifyError:
        from prism.core.types import RefusalReason

        return VerifyError(reason=RefusalReason.VERIFIER_UNAVAILABLE, detail="down", retryable=True)


def _items() -> list[CJBItem]:
    # Two items whose chosen/rejected code carry distinct markers so the fake engine picks a side.
    return [
        CJBItem(
            task="codegen",
            producer="fixtureA",
            item_id="i1",
            question="q1",
            chosen_code="def good1(): return 1  # GOODCODE",
            rejected_code="def bad1(): return 0  # BADCODE",
        ),
        CJBItem(
            task="coderepair",
            producer="fixtureB",
            item_id="i2",
            question="q2",
            chosen_code="def good2(): return 2  # GOODCODE",
            rejected_code="def bad2(): return 9  # BADCODE",
        ),
    ]


# --- loader: offline fixture ---


class TestLoaderOffline:
    def test_fixture_yields_items_with_chosen_ne_rejected(self) -> None:
        items = load_codejudgebench(offline=True)
        assert len(items) >= 6
        for it in items:
            assert it.chosen_code and it.rejected_code
            assert it.chosen_code != it.rejected_code  # a pair must differ
            assert it.task in {"codegen", "codegen_pass5", "coderepair", "testgen"}

    def test_task_filter(self) -> None:
        codegen = load_codejudgebench(offline=True, task="codegen")
        assert codegen  # the fixture has codegen items
        assert all(it.task == "codegen" for it in codegen)

    def test_limit_caps_the_slice(self) -> None:
        assert len(load_codejudgebench(offline=True, limit=2)) == 2

    def test_default_fixture_exists(self) -> None:
        assert DEFAULT_FIXTURE.exists()

    def test_andon_raises_on_missing_column(self, tmp_path: Path) -> None:
        # A broken fixture row WITHOUT pos_response's source column must ANDON-fail (never silently
        # mis-map chosen/rejected — the #1 risk). Feed an inline broken row.
        broken = tmp_path / "broken.jsonl"
        broken.write_text(
            json.dumps({"task": "codegen", "question_content": "q", "neg_response": "bad"}) + "\n",
            encoding="utf-8",
        )
        with pytest.raises(CJBColumnError) as exc:
            load_codejudgebench_offline(source=broken)
        assert "pos_response" in str(exc.value)

    def test_content_hash_is_order_independent(self) -> None:
        items = load_codejudgebench(offline=True)
        assert cjb_content_hash(items) == cjb_content_hash(list(reversed(items)))

    def test_content_hash_changes_on_content_edit(self) -> None:
        items = load_codejudgebench(offline=True)
        h0 = cjb_content_hash(items)
        mutated = [*items[:-1], CJBItem(**{**items[-1].to_dict(), "chosen_code": "changed"})]
        assert cjb_content_hash(mutated) != h0


# --- loader: online contract (no network is hit; we only check the guards) ---


class TestLoaderOnlineGuards:
    def test_online_requires_task(self) -> None:
        with pytest.raises(ValueError, match="needs an explicit task"):
            load_codejudgebench(offline=False, task=None)

    def test_online_rejects_unknown_task(self) -> None:
        with pytest.raises(ValueError, match="unknown CodeJudgeBench task"):
            load_codejudgebench(offline=False, task="not_a_task")


# --- harness: the chosen-vs-rejected reduction (the #1 risk, both directions) ---


class TestHarnessAccuracy:
    @pytest.mark.asyncio
    async def test_prefer_chosen_gives_accuracy_one(self) -> None:
        engine = _PreferEngine("GOODCODE")  # accepts the chosen side
        results = await run_codejudgebench(engine, _items(), n_runs=3)
        summary = summarize_codejudgebench(results)
        assert summary.overall.accuracy == 1.0
        assert summary.overall.correct == 2
        assert summary.overall.tie_rate == 0.0

    @pytest.mark.asyncio
    async def test_prefer_rejected_gives_accuracy_zero(self) -> None:
        # Swap-detector: an engine preferring the REJECTED side must score 0.0, proving the loader
        # did not silently swap chosen<->rejected (an inversion that would look like a great score).
        engine = _PreferEngine("BADCODE")  # accepts the rejected side
        results = await run_codejudgebench(engine, _items(), n_runs=3)
        summary = summarize_codejudgebench(results)
        assert summary.overall.accuracy == 0.0
        assert summary.overall.correct == 0

    @pytest.mark.asyncio
    async def test_tie_counted_wrong_and_surfaced_in_tie_rate(self) -> None:
        engine = _TieEngine()  # identical verdict+confidence on both sides -> tie
        results = await run_codejudgebench(engine, _items(), n_runs=3)
        summary = summarize_codejudgebench(results)
        assert summary.overall.accuracy == 0.0  # a tie is WRONG in the headline number
        assert summary.overall.tie_rate == 1.0  # but surfaced separately
        assert all(r.is_tie and not r.correct for r in results)

    @pytest.mark.asyncio
    async def test_position_consistency_computed(self) -> None:
        engine = _PreferEngine("GOODCODE")
        results = await run_codejudgebench(engine, _items(), n_runs=3, both_orders=True)
        summary = summarize_codejudgebench(results)
        # A verdict-rank-driven preference is order-independent, so both orders agree -> 1.0.
        assert summary.position_consistency == 1.0
        lo, hi = summary.position_consistency_ci
        assert 0.0 <= lo <= hi <= 1.0

    @pytest.mark.asyncio
    async def test_unavailable_excluded_from_accuracy(self) -> None:
        engine = _UnavailableEngine()
        results = await run_codejudgebench(engine, _items(), n_runs=3)
        summary = summarize_codejudgebench(results)
        assert summary.n_items == 0  # nothing scored
        assert summary.n_unavailable == 2
        assert summary.overall.accuracy == 0.0  # no division blow-up
        assert any("unavailable" in n for n in summary.notes)

    @pytest.mark.asyncio
    async def test_per_task_and_per_producer_buckets(self) -> None:
        engine = _PreferEngine("GOODCODE")
        results = await run_codejudgebench(engine, _items(), n_runs=3)
        summary = summarize_codejudgebench(results)
        tasks = {p.label for p in summary.per_task}
        producers = {p.label for p in summary.per_producer}
        assert tasks == {"codegen", "coderepair"}
        assert producers == {"fixtureA", "fixtureB"}


class TestPairwisePreferExercised:
    """pairwise_prefer had ZERO callers before this build; confirm the harness drives it."""

    @pytest.mark.asyncio
    async def test_harness_uses_pairwise_prefer(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import prism.eval.benchmarks.harness as harness_mod

        calls: list[tuple[str, str]] = []
        real = harness_mod.pairwise_prefer

        def _spy(va: str, ca: float, vb: str, cb: float) -> str:
            calls.append((va, vb))
            return real(va, ca, vb, cb)

        monkeypatch.setattr(harness_mod, "pairwise_prefer", _spy)
        engine = _PreferEngine("GOODCODE")
        await run_codejudgebench(engine, _items()[:1], n_runs=1, both_orders=True)
        # both orders -> 2 reductions for the single item.
        assert len(calls) == 2
