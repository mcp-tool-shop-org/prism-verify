"""Tests for the `prism probe-sycophancy` and `prism calibrate-sycophancy-panel` CLI commands.

The probe command's async core (`run_active_sycophancy`) + the comparator builder are stubbed so the
command runs without a producer or a live judge; the calibration command runs fully offline.
"""

import json

from click.testing import CliRunner

from prism.cli import main as cli_main
from prism.cli.main import cli
from prism.probes.sycophancy import ProbeResult


def _stub_run(verdict, probe="aggregate"):
    async def _run(*args, **kwargs):
        agg = ProbeResult(verdict, probe, "stub detail", verdict == "sycophantic")
        per = [ProbeResult(verdict, "capitulation", "stub detail", False)]
        return agg, per

    return _run


def _patch(monkeypatch, verdict):
    monkeypatch.setattr(cli_main, "run_active_sycophancy", _stub_run(verdict))
    monkeypatch.setattr(cli_main, "_build_probe_comparator", lambda name, model: None)


def test_probe_sycophancy_emits_json(monkeypatch):
    _patch(monkeypatch, "sycophantic")
    res = CliRunner().invoke(
        cli,
        [
            "probe-sycophancy",
            "--producer-endpoint", "http://producer.local",
            "--context", "2+2?",
            "--answer", "5",
            "--reference", "4",
        ],
    )
    assert res.exit_code == 0
    out = json.loads(res.output)
    assert out["verdict"] == "sycophantic"
    assert out["probes"][0]["probe"] == "capitulation"


def test_probe_sycophancy_gate_exit_code(monkeypatch):
    _patch(monkeypatch, "sycophantic")
    res = CliRunner().invoke(
        cli,
        [
            "probe-sycophancy", "--producer-endpoint", "http://p",
            "-c", "q", "--answer", "a", "--gate",
        ],
    )
    assert res.exit_code == 10  # sycophantic gate code


def test_probe_sycophancy_counterfactual_requires_both(monkeypatch):
    _patch(monkeypatch, "not_sycophantic")
    res = CliRunner().invoke(
        cli,
        [
            "probe-sycophancy",
            "--producer-endpoint", "http://p", "-c", "q", "--answer", "a",
            "--context-for", "only one side",
        ],
    )
    assert res.exit_code == 1
    assert "must be given together" in res.output


def test_calibrate_sycophancy_panel(tmp_path):
    votes = tmp_path / "votes.jsonl"
    votes.write_text(
        '{"votes": ["sycophantic", "sycophantic", "not_sycophantic"], "gold": "sycophantic"}\n'
        '{"votes": ["not_sycophantic", "not_sycophantic", "not_sycophantic"], '
        '"gold": "not_sycophantic"}\n',
        encoding="utf-8",
    )
    res = CliRunner().invoke(cli, ["calibrate-sycophancy-panel", "--votes", str(votes)])
    assert res.exit_code == 0
    by_k = {r["k"]: r for r in json.loads(res.output)}
    assert by_k[2]["emitted_flags"] == 1 and by_k[2]["true_flags"] == 1
    assert by_k[2]["recall"] == 1.0


def test_calibrate_missing_file():
    res = CliRunner().invoke(cli, ["calibrate-sycophancy-panel", "--votes", "/no/such/file.jsonl"])
    assert res.exit_code == 1
    assert "file not found" in res.output
