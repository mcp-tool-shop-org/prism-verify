"""Tests for receipt store."""

import hashlib
import hmac
import json
import sqlite3
from datetime import timedelta

import pytest

from prism.core.types import ReasoningVisibility
from prism.receipts.store import ReceiptStore


@pytest.fixture
def store(tmp_path):
    """Create a receipt store with a temp database."""
    db_path = tmp_path / "test_receipts.db"
    s = ReceiptStore(db_path=db_path, signing_secret=b"test-secret")
    yield s
    s.close()


class TestReceiptStore:
    def test_create_receipt(self, store):
        receipt = store.create_receipt(
            pre_strip_hash="aaa",
            post_strip_hash="bbb",
            verifier_models=["gemini-2.5-pro"],
            pairwise_rho={"L1,L2": 0.15},
            reasoning_visibility_mode=ReasoningVisibility.STRIPPED,
            verdict="accept",
            confidence=0.9,
            retryable=False,
            lens_results_json="[]",
        )
        assert receipt.id.startswith("prism-")
        assert receipt.pre_strip_hash == "aaa"
        assert receipt.post_strip_hash == "bbb"
        assert receipt.signature != ""

    def test_get_receipt(self, store):
        receipt = store.create_receipt(
            pre_strip_hash="xxx",
            post_strip_hash="yyy",
            verifier_models=["model-a"],
            pairwise_rho={},
            reasoning_visibility_mode=ReasoningVisibility.STRIPPED,
            verdict="refuse",
            confidence=0.95,
            retryable=False,
            lens_results_json="[]",
        )

        fetched = store.get_receipt(receipt.id)
        assert fetched is not None
        assert fetched["id"] == receipt.id
        assert fetched["verdict"] == "refuse"

    def test_get_nonexistent_receipt(self, store):
        assert store.get_receipt("prism-nonexistent") is None

    def test_verify_signature_valid(self, store):
        receipt = store.create_receipt(
            pre_strip_hash="hash1",
            post_strip_hash="hash2",
            verifier_models=["model"],
            pairwise_rho={"L1,L2": 0.1},
            reasoning_visibility_mode=ReasoningVisibility.STRIPPED,
            verdict="accept",
            confidence=0.85,
            retryable=False,
            lens_results_json="[]",
        )
        assert store.verify_signature(receipt.id) is True

    def test_verify_signature_invalid_id(self, store):
        assert store.verify_signature("prism-does-not-exist") is False


class TestReceiptSigningScope:
    """v0.2.0 signs the lens_prompt_hashes PIN and the previously-unsigned fields."""

    def test_lens_prompt_hashes_persisted_and_returned(self, store):
        r = store.create_receipt(
            pre_strip_hash="a",
            post_strip_hash="b",
            verifier_models=["gemini-2.5-pro"],
            pairwise_rho={},
            reasoning_visibility_mode=ReasoningVisibility.STRIPPED,
            verdict="accept",
            confidence=0.9,
            retryable=False,
            lens_results_json="[]",
            lens_prompt_hashes={"contract_completeness": "deadbeef", "invariant": "cafef00d"},
        )
        assert r.lens_prompt_hashes == {
            "contract_completeness": "deadbeef",
            "invariant": "cafef00d",
        }
        assert r.schema_version == 2
        fetched = store.get_receipt(r.id)
        assert json.loads(fetched["lens_prompt_hashes"]) == r.lens_prompt_hashes
        assert store.verify_signature(r.id) is True

    def test_tampering_lens_prompt_hashes_breaks_signature(self, store):
        # The PIN must be UNDER the signature, else it is tamper-theatre.
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
            lens_prompt_hashes={"contract": "aaaa"},
        )
        store._conn.execute(
            "UPDATE receipts SET lens_prompt_hashes = ? WHERE id = ?",
            (json.dumps({"contract": "bbbb"}), r.id),
        )
        store._conn.commit()
        assert store.verify_signature(r.id) is False

    @pytest.mark.parametrize(
        "column,value",
        [
            ("verdict", "refuse"),
            ("confidence", 0.1),
            ("retryable", 1),
            ("reasoning_visibility_mode", "conservative"),
            ("lens_results", '[{"tampered": true}]'),
        ],
    )
    def test_tampering_any_signed_field_breaks_signature(self, store, column, value):
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
        store._conn.execute(f"UPDATE receipts SET {column} = ? WHERE id = ?", (value, r.id))
        store._conn.commit()
        assert store.verify_signature(r.id) is False

    def test_tampering_unsigned_created_at_keeps_signature_valid(self, store):
        # created_at is local bookkeeping, intentionally NOT signed.
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
        store._conn.execute("UPDATE receipts SET created_at = ? WHERE id = ?", ("1999-01-01", r.id))
        store._conn.commit()
        assert store.verify_signature(r.id) is True


_V01_SCHEMA = """
CREATE TABLE receipts (
    id TEXT PRIMARY KEY,
    pre_strip_hash TEXT NOT NULL,
    post_strip_hash TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    verifier_models TEXT NOT NULL,
    pairwise_rho TEXT NOT NULL,
    reasoning_visibility_mode TEXT NOT NULL,
    verdict TEXT NOT NULL,
    confidence REAL NOT NULL,
    retryable INTEGER NOT NULL,
    lens_results TEXT NOT NULL,
    signature TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


class TestSchemaMigration:
    """Opening a v0.1 receipts.db must upgrade it without breaking legacy signatures."""

    def test_migrates_and_preserves_legacy_v1_signature(self, tmp_path):
        secret = b"test-secret"
        db = tmp_path / "old.db"

        # Write a v0.1-shaped DB with one row, signed exactly as v0.1 did (7 fields).
        conn = sqlite3.connect(str(db))
        conn.executescript(_V01_SCHEMA)
        legacy_sign = {
            "id": "prism-legacy-1",
            "pre_strip_hash": "aa",
            "post_strip_hash": "bb",
            "timestamp": "2026-05-01T00:00:00+00:00",
            "verifier_models": ["gemini-2.5-pro"],
            "pairwise_rho": {"L1,L2": 0.1},
            "verdict": "accept",
        }
        canonical = json.dumps(legacy_sign, sort_keys=True, separators=(",", ":"))
        legacy_sig = hmac.new(secret, canonical.encode(), hashlib.sha256).hexdigest()
        conn.execute(
            """INSERT INTO receipts
               (id, pre_strip_hash, post_strip_hash, timestamp, verifier_models,
                pairwise_rho, reasoning_visibility_mode, verdict, confidence,
                retryable, lens_results, signature)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                "prism-legacy-1",
                "aa",
                "bb",
                "2026-05-01T00:00:00+00:00",
                json.dumps(["gemini-2.5-pro"]),
                json.dumps({"L1,L2": 0.1}),
                "stripped",
                "accept",
                0.9,
                0,
                "[]",
                legacy_sig,
            ),
        )
        conn.commit()
        conn.close()

        # Opening with the v0.2 store migrates the schema in place.
        store = ReceiptStore(db_path=db, signing_secret=secret)
        # Legacy row keeps its original (v1) signature valid.
        assert store.verify_signature("prism-legacy-1") is True
        # A fresh v2 receipt with a PIN also verifies in the same upgraded DB.
        r = store.create_receipt(
            pre_strip_hash="cc",
            post_strip_hash="dd",
            verifier_models=["claude-sonnet-4-6"],
            pairwise_rho={},
            reasoning_visibility_mode=ReasoningVisibility.STRIPPED,
            verdict="revise",
            confidence=0.7,
            retryable=True,
            lens_results_json="[]",
            lens_prompt_hashes={"contract": "abc123"},
        )
        assert r.schema_version == 2
        assert store.verify_signature(r.id) is True
        # Legacy row reads back with backfilled defaults.
        legacy = store.get_receipt("prism-legacy-1")
        assert legacy["schema_version"] == 1
        assert json.loads(legacy["lens_prompt_hashes"]) == {}
        store.close()


class TestReceiptCompensators:
    """receipt delete / prune — the named compensators for the receipt INSERT."""

    def _mk(self, store, verdict="accept"):
        return store.create_receipt(
            pre_strip_hash="a",
            post_strip_hash="b",
            verifier_models=["m"],
            pairwise_rho={},
            reasoning_visibility_mode=ReasoningVisibility.STRIPPED,
            verdict=verdict,
            confidence=0.9,
            retryable=False,
            lens_results_json="[]",
        )

    def test_delete_existing_returns_true(self, store):
        r = self._mk(store)
        assert store.delete_receipt(r.id) is True
        assert store.get_receipt(r.id) is None

    def test_delete_missing_returns_false(self, store):
        assert store.delete_receipt("prism-nope") is False

    def test_prune_by_utc_timestamp_is_selective(self, store):
        recent = self._mk(store, verdict="accept")
        old = self._mk(store, verdict="refuse")
        store._conn.execute(
            "UPDATE receipts SET timestamp = ? WHERE id = ?",
            ("2020-01-01T00:00:00+00:00", old.id),
        )
        store._conn.commit()
        assert store.prune(timedelta(days=30)) == 1
        assert store.get_receipt(old.id) is None
        assert store.get_receipt(recent.id) is not None
