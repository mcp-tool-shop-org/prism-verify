"""Integration test: the eval runner drives the real engine and scores samples correctly.

Uses a scripted ``MockProvider`` (fails on a planted-bug marker) over a tiny hand-built corpus, so
the whole path — engine.verify -> per-lens outcomes -> report metrics -> rendering — is exercised
deterministically with no real provider calls.
"""

from __future__ import annotations

import json

import pytest

from prism.core.engine import VerificationEngine
from prism.core.setup import register_default_lenses
from prism.eval.corpus import Sample
from prism.eval.report import render_json, render_markdown, summarize
from prism.eval.runner import MockProvider, run_eval
from prism.lenses.registry import clear_registry
from prism.receipts.store import ReceiptStore

_MARKER = "PLANTED_BUG"


def _samples() -> list[Sample]:
    return [
        Sample(
            id="t-inv-bug",
            artifact_type="code",
            content=f"def last(xs):\n    # {_MARKER}\n    return xs[len(xs)]\n",
            intent="Return the last element of a non-empty list.",
            positive=True,
            target_lens="invariant",
            bug_class="off_by_one",
            expected_verdict="refuse",
            split="public",
        ),
        Sample(
            id="t-inv-clean",
            artifact_type="code",
            content="def last(xs):\n    return xs[len(xs) - 1]\n",
            intent="Return the last element of a non-empty list.",
            positive=False,
            target_lens="invariant",
            bug_class="clean",
            expected_verdict="accept",
            split="public",
        ),
        Sample(
            id="t-con-bug",
            artifact_type="code",
            content=f"def avg(xs):\n    # {_MARKER}\n    return sum(xs) / len(xs)\n",
            intent="Average a list; return 0.0 for an empty list.",
            positive=True,
            target_lens="contract_completeness",
            bug_class="missing_clause",
            expected_verdict="refuse",
            split="public",
        ),
        Sample(
            id="t-con-clean",
            artifact_type="code",
            content="def avg(xs):\n    return sum(xs) / len(xs) if xs else 0.0\n",
            intent="Average a list; return 0.0 for an empty list.",
            positive=False,
            target_lens="contract_completeness",
            bug_class="clean",
            expected_verdict="accept",
            split="public",
        ),
    ]


def _policy(lens: str, artifact: str) -> tuple[str, float]:
    """Fail when the planted-bug marker is present (any lens), else pass."""
    return ("fail", 0.9) if _MARKER in artifact else ("pass", 0.8)


@pytest.fixture
def engine(tmp_path):  # type: ignore[no-untyped-def]
    clear_registry()
    register_default_lenses()
    store = ReceiptStore(db_path=tmp_path / "eval.db", signing_secret=b"test-eval-secret")
    eng = VerificationEngine(providers={"local": MockProvider(_policy)}, receipt_store=store)
    try:
        yield eng
    finally:
        store.close()
        clear_registry()


async def test_runner_records_per_lens_outcomes_and_verdicts(engine: VerificationEngine) -> None:
    run = await run_eval(
        engine, _samples(), caller_family="anthropic", n_runs=1, verifier_label="test-mock"
    )
    rec = {r.sample_id: r for r in run.records}

    # The planted bug makes the target lens FAIL; the clean counterpart PASSes.
    assert rec["t-inv-bug"].per_lens["invariant"] == "fail"
    assert rec["t-inv-clean"].per_lens["invariant"] == "pass"
    assert rec["t-con-bug"].per_lens["contract_completeness"] == "fail"
    assert rec["t-con-clean"].per_lens["contract_completeness"] == "pass"

    # Buggy -> off-accept verdict; clean -> accept. No lens errored.
    assert rec["t-inv-bug"].verdict in {"refuse", "revise", "escalate"}
    assert rec["t-inv-clean"].verdict == "accept"
    assert not rec["t-inv-bug"].errored

    # Distinct per-lens finding categories => rho 0 => no spurious collapse.
    assert all(v == 0.0 for v in rec["t-inv-bug"].pairwise_rho.values())


async def test_report_scores_and_renders(engine: VerificationEngine) -> None:
    run = await run_eval(engine, _samples(), n_runs=1, verifier_label="test-mock")
    report = summarize(run)

    inv = next(lr for lr in report.per_lens if lr.lens == "invariant")
    assert inv.recall == 1.0  # caught its planted bug
    assert inv.specificity == 1.0  # quiet on the clean counterpart
    assert inv.mcc == 1.0

    # Verdict accuracy is perfect on this scripted set (buggy->off-accept, clean->accept).
    assert report.verdict_accuracy_overall == 1.0
    # Offline/mock note present; small-N note present.
    assert any("MOCK" in n for n in report.notes)

    md = render_markdown(report)
    assert "Per-lens quality" in md and "Submodular coverage" in md
    assert all(ord(c) < 128 for c in md)  # ASCII-safe (no console encode crash)
    json.loads(render_json(report))  # valid JSON


async def test_runner_rejects_zero_runs(engine: VerificationEngine) -> None:
    with pytest.raises(ValueError):
        await run_eval(engine, _samples(), n_runs=0)
