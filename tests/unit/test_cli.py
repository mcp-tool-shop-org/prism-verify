"""Tests for the prism CLI receipt commands and duration parsing."""

from __future__ import annotations

import json
from datetime import timedelta

import pytest
from click.testing import CliRunner

from prism.cli.main import _parse_duration, cli
from prism.core.types import ReasoningVisibility
from prism.receipts.store import ReceiptStore


def _seed_receipt(db_path) -> str:
    store = ReceiptStore(db_path=db_path, signing_secret=b"test-secret")
    r = store.create_receipt(
        pre_strip_hash="a",
        post_strip_hash="b",
        verifier_models=["m"],
        pairwise_rho={},
        reasoning_visibility_mode=ReasoningVisibility.STRIPPED,
        verdict="accept",
        confidence=0.9,
        retryable=False,
        lens_results_json="[]",
    )
    store.close()
    return r.id


class TestParseDuration:
    @pytest.mark.parametrize(
        "text,seconds",
        [("90d", 90 * 86400), ("24h", 24 * 3600), ("30m", 1800), ("45s", 45), ("2w", 2 * 604800)],
    )
    def test_valid(self, text, seconds):
        assert _parse_duration(text) == timedelta(seconds=seconds)

    @pytest.mark.parametrize("bad", ["", "90", "10x", "abc", "d"])
    def test_invalid_raises(self, bad):
        with pytest.raises(Exception):
            _parse_duration(bad)


class TestReceiptCli:
    def test_delete_existing(self, tmp_path, monkeypatch):
        db = tmp_path / "cli.db"
        rid = _seed_receipt(db)
        monkeypatch.setenv("PRISM_DEV", "1")
        monkeypatch.setattr("prism.receipts.store.DEFAULT_DB_PATH", db)
        result = CliRunner().invoke(cli, ["receipt", "delete", rid])
        assert result.exit_code == 0
        assert json.loads(result.output)["deleted"] == rid

    def test_delete_missing_exits_1(self, tmp_path, monkeypatch):
        db = tmp_path / "cli.db"
        _seed_receipt(db)
        monkeypatch.setenv("PRISM_DEV", "1")
        monkeypatch.setattr("prism.receipts.store.DEFAULT_DB_PATH", db)
        result = CliRunner().invoke(cli, ["receipt", "delete", "prism-nope"])
        assert result.exit_code == 1

    def test_prune_requires_yes(self, tmp_path, monkeypatch):
        db = tmp_path / "cli.db"
        _seed_receipt(db)
        monkeypatch.setenv("PRISM_DEV", "1")
        monkeypatch.setattr("prism.receipts.store.DEFAULT_DB_PATH", db)
        result = CliRunner().invoke(cli, ["receipt", "prune", "--older-than", "1d"])
        assert result.exit_code == 1
        # Without --yes, nothing is deleted.
        store = ReceiptStore(db_path=db, signing_secret=b"test-secret")
        remaining = store._conn.execute("SELECT COUNT(*) FROM receipts").fetchone()[0]
        store.close()
        assert remaining == 1

    def test_prune_with_yes_removes_old(self, tmp_path, monkeypatch):
        db = tmp_path / "cli.db"
        _seed_receipt(db)
        monkeypatch.setenv("PRISM_DEV", "1")
        monkeypatch.setattr("prism.receipts.store.DEFAULT_DB_PATH", db)
        result = CliRunner().invoke(cli, ["receipt", "prune", "--older-than", "0s", "--yes"])
        assert result.exit_code == 0
        assert json.loads(result.output)["pruned"] == 1
