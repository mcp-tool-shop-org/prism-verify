"""Integration: `prism eval --offline --family-ab` proves the Lock-1 A/B wiring end-to-end.

The historical bug (F-01): the same-family control routed the caller family back to itself, but the
unconditional Lock-1 gate exhausted the only candidate -> RoutingError -> every control adjudication
returned VERIFIER_UNAVAILABLE -> the control accuracy was 0.0 over ZERO rows, so delta = fd - 0.0
measured nothing, silently. This test locks the fix: an offline run produces a DETERMINISTIC,
SIGNED-POSITIVE delta over a non-zero paired set, with both arms' provenance and the McNemar CI in
the report, and the corpus-hash-parity assertion holding.
"""

from __future__ import annotations

import json

from click.testing import CliRunner

from prism.cli.main import cli
from prism.eval.corpus import build_corpus, corpus_content_hash, load_corpus


def _build_offline_corpus(tmp_path):  # type: ignore[no-untyped-def]
    corpus = tmp_path / "corpus"
    build_corpus(corpus)
    return corpus


def test_offline_family_ab_yields_positive_delta_and_full_report(tmp_path, monkeypatch) -> None:
    # Keep the offline run hermetic: no env-configured providers leak into the control path.
    for key in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GOOGLE_API_KEY"):
        monkeypatch.delenv(key, raising=False)

    corpus = _build_offline_corpus(tmp_path)
    out = tmp_path / "report"
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "eval",
            "--corpus",
            str(corpus),
            "--split",
            "public",
            "--offline",
            "--family-ab",
            "--runs",
            "1",
            "--report",
            "json",
            "--out",
            str(out),
        ],
    )
    assert result.exit_code == 0, result.output

    report = json.loads((out / "report.json").read_text(encoding="utf-8"))
    ab = report["family_ab"]
    assert ab is not None, "family_ab block missing — the A/B did not run"

    # (1) Non-zero paired set: the control arm actually produced verdicts (the bug produced zero).
    assert ab["n_paired"] > 0

    # (2) Deterministic SIGNED POSITIVE delta: the family-different treatment beats the
    #     self-preferring (over-accepting) same-family control.
    assert ab["delta"] > 0.0
    assert ab["family_different_correct"] > ab["same_family_correct"]

    # (3) Paired McNemar CI present and well-formed (lo <= delta <= hi within clamp).
    lo, hi = ab["delta_ci"]
    assert lo <= ab["delta"] <= hi

    # (4) Both arms' resolved model ids are named (provenance for the delta).
    assert ab["family_different_model_ids"], "treatment arm model ids missing"
    assert ab["same_family_model_ids"] == ["anthropic-control"]

    # (5) Markdown surface carries the same facts a reader needs.
    md = (out / "report.md").read_text(encoding="utf-8")
    assert "Family-different vs same-family (Lock 1 A/B)" in md
    assert "Paired samples" in md
    assert "95% CI" in md
    assert "anthropic-control" in md


def test_offline_family_ab_corpus_hash_parity_holds(tmp_path, monkeypatch) -> None:
    """Both arms are scored over the SAME corpus content-hash (the ANDON parity check passes)."""
    for key in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GOOGLE_API_KEY"):
        monkeypatch.delenv(key, raising=False)

    corpus = _build_offline_corpus(tmp_path)
    out = tmp_path / "report"
    samples = load_corpus(corpus, "public")
    expected_hash = corpus_content_hash(samples)

    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "eval",
            "--corpus",
            str(corpus),
            "--split",
            "public",
            "--offline",
            "--family-ab",
            "--runs",
            "1",
            "--report",
            "json",
            "--out",
            str(out),
        ],
    )
    assert result.exit_code == 0, result.output

    report = json.loads((out / "report.json").read_text(encoding="utf-8"))
    # The treatment run records the corpus content-hash; the control arm asserted parity at runtime
    # (a mismatch would have raised an ANDON ClickException -> non-zero exit, caught above).
    assert report["corpus_content_hash"] == expected_hash
