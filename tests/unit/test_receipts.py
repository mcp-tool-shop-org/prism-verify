"""Tests for receipt store."""

import hashlib
import hmac
import json
import sqlite3
import threading
from datetime import timedelta

import pytest

from prism.core.types import ReasoningVisibility
from prism.receipts.store import ReceiptStore, SigningSecretError


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
        assert r.schema_version == 5
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
            ("artifact_type", "citations"),
            ("retrieval_pins", '[{"id": "x"}]'),
            # TEST-A-008: kid is signed (v4+), so flipping it must break the signature — a
            # tamperer cannot rewrite the key id a receipt claims to be signed under.
            ("kid", "ed25519-deadbeefdeadbeef"),
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


class TestNonFiniteRefusedAtSignTime:
    """RCPT-A-002: NaN / Infinity confidence or pairwise_rho is refused at create time."""

    def _mk(self, store, **over):
        kwargs = dict(
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
        kwargs.update(over)
        return store.create_receipt(**kwargs)

    @pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
    def test_non_finite_confidence_is_refused(self, store, bad):
        # A NaN/Infinity would serialize to the bare literal NaN/Infinity (invalid JSON), yielding
        # a signed payload no standards-compliant verifier could parse — refuse at the boundary.
        with pytest.raises(ValueError):
            self._mk(store, confidence=bad)

    @pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
    def test_non_finite_pairwise_rho_is_refused(self, store, bad):
        with pytest.raises(ValueError):
            self._mk(store, pairwise_rho={"L1,L2": bad})

    def test_no_partial_row_written_when_refused(self, store):
        # The refusal happens before the INSERT, so a rejected receipt leaves no row behind.
        before = store._conn.execute("SELECT COUNT(*) FROM receipts").fetchone()[0]
        with pytest.raises(ValueError):
            self._mk(store, confidence=float("nan"))
        after = store._conn.execute("SELECT COUNT(*) FROM receipts").fetchone()[0]
        assert after == before


class TestV5SignedZeroNormalization:
    """Second-hardening round: IEEE-754 ``-0.0`` must canonicalize to ``0.000000000000``.

    SQLite's REAL column drops the sign bit, so a ``-0.0`` confidence would sign one way and
    read back ``+0.0`` and desync prism's OWN verify; and Python's Decimal/repr render ``-0.0``
    as ``-0.000000000000`` while JS ``(-0).toFixed(12)`` yields ``0.000000000000`` (cross-tool
    divergence). ``_v5_number`` normalizes ``-0.0`` -> ``+0.0`` BEFORE formatting to close both.
    """

    def test_v5_number_normalizes_negative_zero(self):
        from prism.receipts.store import _v5_number

        # The exact byte the spec promises (and the SQLite read-back, and JS toFixed) all agree.
        assert _v5_number(-0.0) == "0.000000000000"
        # +0.0 and -0.0 collapse to the identical string — no sign-bit divergence in the bytes.
        assert _v5_number(0.0) == _v5_number(-0.0)

    def test_self_verify_with_negative_zero_confidence_and_rho(self, store):
        # A receipt carrying -0.0 in BOTH float fields must self-verify: the signed bytes use the
        # normalized 0.000000000000, and the SQLite REAL read-back (+0.0) reproduces the same
        # normalized bytes. Without normalization the sign would desync and this would be False.
        r = store.create_receipt(
            pre_strip_hash="a",
            post_strip_hash="b",
            verifier_models=["m"],
            pairwise_rho={"L1,L2": -0.0},
            reasoning_visibility_mode=ReasoningVisibility.STRIPPED,
            verdict="accept",
            confidence=-0.0,
            retryable=False,
            lens_results_json="[]",
        )
        assert store.verify_signature(r.id) is True
        # Confidence reads back as +0.0 from the REAL column (sign bit dropped) — proof the
        # canonicalizer cannot rely on the stored sign and MUST normalize.
        row = store.get_receipt(r.id)
        assert row["confidence"] == 0.0

    def test_negative_and_positive_zero_canonicalize_identically(self):
        # -0.0 vs +0.0 in confidence/pairwise_rho must produce byte-identical v5 canonical bytes.
        from prism.receipts.store import _build_sign_data, _canonical_v5

        def _sign_data(zero):
            return _build_sign_data(
                schema_version=5,
                receipt_id="prism-zero",
                pre_strip_hash="a",
                post_strip_hash="b",
                timestamp="2026-06-02T00:00:00+00:00",
                verifier_models=["m"],
                pairwise_rho={"L1,L2": zero},
                verdict="accept",
                reasoning_visibility_mode="stripped",
                confidence=zero,
                retryable=False,
                lens_results_json="[]",
                lens_prompt_hashes={},
            )

        assert _canonical_v5(_sign_data(-0.0)) == _canonical_v5(_sign_data(0.0))


class TestV5Canonicalization:
    """RCPT-A-001: fresh receipts are v5 + a CROSS-TOOL byte-identity proof of the v5 rule."""

    def test_fresh_receipt_is_v5_and_verifies(self, store):
        r = store.create_receipt(
            pre_strip_hash="aaa",
            post_strip_hash="bbb",
            verifier_models=["gemini-2.5-pro"],
            pairwise_rho={"L1,L2": 0.1},
            reasoning_visibility_mode=ReasoningVisibility.STRIPPED,
            verdict="accept",
            confidence=0.9,
            retryable=False,
            lens_results_json="[]",
        )
        assert r.schema_version == 5
        assert store.verify_signature(r.id) is True

    def test_third_party_can_reproduce_the_v5_canonical_bytes(self, store):
        """Independently reconstruct the v5 canonical bytes from ONLY the documented rule
        (sorted keys recursively, tight separators, ensure_ascii=False, bool->true/false,
        ints bare, floats emitted by a ``toFixed``-equivalent: round-half-even to 12 fractional
        places AND sign-normalized so ``-0.0`` -> ``0.000000000000``) and prove HMAC over those
        bytes equals the signature the signer wrote. If a third party (role-os, a Go/JS tool)
        follows the spec, it reproduces the exact signed bytes.

        Hardening (second round): the encoder below deliberately does NOT reuse Python's
        ``Decimal(x).quantize(...HALF_EVEN)`` + ``f"{q:.12f}"`` recipe — that renders ``-0.0`` as
        ``-0.000000000000``, identical to a HYPOTHETICAL un-normalized production, so it would
        test Python==Python and miss the signed-zero divergence. Instead it sign-normalizes (the
        ``toFixed`` / Go ``%.12f`` / Rust ``{:.12}`` semantics for ``-0.0``), and the receipt
        carries a ``-0.0`` pairwise_rho. So this test FAILS if production ever stops normalizing
        signed zero (the production bytes would then differ from this independent encoder's).
        """
        secret = b"test-secret"  # matches the `store` fixture's signing_secret
        # Non-trivial floats that exercise the round-half-even + fixed-12-places rule, a signed
        # zero (-0.0) that exercises the normalization, plus a non-ASCII string to prove
        # ensure_ascii=False (literal UTF-8, not \uXXXX).
        r = store.create_receipt(
            pre_strip_hash="café",  # non-ASCII → must be literal UTF-8 in the canonical bytes
            post_strip_hash="bbb",
            verifier_models=["m"],
            pairwise_rho={
                "L1,L2": 1 / 3,
                "L1,L3": 0.30000000000000004,
                "L1,L4": -0.0,  # signed zero — the load-bearing addition vs the wave-2 test
            },
            reasoning_visibility_mode=ReasoningVisibility.STRIPPED,
            verdict="accept",
            confidence=0.9,
            retryable=False,
            lens_results_json="[]",
            lens_prompt_hashes={"contract": "abc123"},
        )
        row = store.get_receipt(r.id)

        # --- Independent v5 encoder (NO import from prism.receipts.store) ---
        def num(x: float) -> str:
            # toFixed(12)-equivalent: EXACTLY 12 fractional digits, round-half-to-even, and a
            # SIGN-NORMALIZED zero. ``format(x, ".12f")`` is the cross-language rounding rule;
            # ``abs(x) if x == 0`` collapses -0.0 -> 0.0 the way JS (-0).toFixed(12) does, so this
            # encoder never reproduces a Python-only "-0.000000000000". (NOT Decimal.quantize,
            # whose "-0.000000000000" output would let an un-normalized production slip past.)
            return format(abs(x) if x == 0 else x, ".12f")

        def enc(obj: object) -> str:
            if obj is None:
                return "null"
            if isinstance(obj, bool):
                return "true" if obj else "false"
            if isinstance(obj, float):
                return num(obj)
            if isinstance(obj, int):
                return str(obj)
            if isinstance(obj, str):
                return json.dumps(obj, ensure_ascii=False)
            if isinstance(obj, dict):
                items = sorted(obj.items(), key=lambda kv: kv[0])
                return "{" + ",".join(f"{enc(k)}:{enc(v)}" for k, v in items) + "}"
            if isinstance(obj, (list, tuple)):
                return "[" + ",".join(enc(v) for v in obj) + "]"
            raise TypeError(type(obj))

        # Reconstruct the v5 signed field-set per design/05 (the module docstring).
        sign_data = {
            "id": row["id"],
            "pre_strip_hash": row["pre_strip_hash"],
            "post_strip_hash": row["post_strip_hash"],
            "timestamp": row["timestamp"],
            "verifier_models": json.loads(row["verifier_models"]),
            "pairwise_rho": json.loads(row["pairwise_rho"]),
            "verdict": row["verdict"],
            "reasoning_visibility_mode": row["reasoning_visibility_mode"],
            "confidence": float(row["confidence"]),
            "retryable": bool(row["retryable"]),
            "lens_results_hash": hashlib.sha256(row["lens_results"].encode()).hexdigest(),
            "lens_prompt_hashes": json.loads(row["lens_prompt_hashes"]),
            "schema_version": int(row["schema_version"]),
            "artifact_type": row["artifact_type"],
            "retrieval_pins_hash": hashlib.sha256(
                json.dumps(json.loads(row["retrieval_pins"]), sort_keys=True).encode()
            ).hexdigest(),
            "alg": row["alg"],
            "kid": row["kid"],
        }
        my_bytes = enc(sign_data).encode("utf-8")

        # The signed payload is valid strict JSON (parseable with allow_nan=False).
        json.loads(my_bytes.decode("utf-8"), parse_constant=_reject_constant)
        # Non-ASCII is literal UTF-8, NOT \uXXXX.
        assert "café".encode() in my_bytes
        assert b"\\u00e9" not in my_bytes
        # The fixed-precision float rule is reproduced byte-for-byte.
        assert b"0.333333333333" in my_bytes  # 1/3
        assert b"0.300000000000" in my_bytes  # 0.30000000000000004 rounds down
        assert b"0.900000000000" in my_bytes  # 0.9
        # Signed-zero normalization: the -0.0 rho appears as the POSITIVE 0.000000000000, never
        # "-0.000000000000". If production stopped normalizing, its bytes would carry the negative
        # form, the independent encoder (which normalizes) would not, and the HMAC below diverges.
        assert b"0.000000000000" in my_bytes
        assert b"-0.000000000000" not in my_bytes
        # Byte-identity proof: HMAC over the independently-built bytes == the stored signature.
        expected = hmac.new(secret, my_bytes, hashlib.sha256).hexdigest()
        assert expected == row["signature"]


def _reject_constant(_token: str) -> float:
    raise AssertionError("canonical v5 payload contained a non-finite JSON constant")


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

_V02_SCHEMA = """
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
    lens_prompt_hashes TEXT NOT NULL DEFAULT '{}',
    schema_version INTEGER NOT NULL DEFAULT 2,
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
        # A fresh receipt (current schema, now v5) with a PIN also verifies in the same DB.
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
        assert r.schema_version == 5
        assert store.verify_signature(r.id) is True
        # Legacy row reads back with backfilled defaults.
        legacy = store.get_receipt("prism-legacy-1")
        assert legacy["schema_version"] == 1
        assert json.loads(legacy["lens_prompt_hashes"]) == {}
        store.close()

    def test_migrates_and_preserves_legacy_v2_signature(self, tmp_path):
        # v2 receipts shipped in v0.2.0, so real v2-signed rows exist; they must still verify after
        # the v3 (artifact_type / retrieval_pins) migration, signed over their own field-set.
        from prism.receipts.store import _build_sign_data, _compute_signature

        secret = b"test-secret"
        db = tmp_path / "old_v2.db"
        conn = sqlite3.connect(str(db))
        conn.executescript(_V02_SCHEMA)
        prompt_hashes = {"contract": "abc123"}
        sign = _build_sign_data(
            schema_version=2,
            receipt_id="prism-legacy-v2",
            pre_strip_hash="aa",
            post_strip_hash="bb",
            timestamp="2026-05-15T00:00:00+00:00",
            verifier_models=["gemini-2.5-pro"],
            pairwise_rho={"L1,L2": 0.1},
            verdict="accept",
            reasoning_visibility_mode="stripped",
            confidence=0.9,
            retryable=False,
            lens_results_json="[]",
            lens_prompt_hashes=prompt_hashes,
        )
        sig = _compute_signature(sign, secret)
        conn.execute(
            """INSERT INTO receipts
               (id, pre_strip_hash, post_strip_hash, timestamp, verifier_models, pairwise_rho,
                reasoning_visibility_mode, verdict, confidence, retryable, lens_results,
                lens_prompt_hashes, schema_version, signature)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                "prism-legacy-v2", "aa", "bb", "2026-05-15T00:00:00+00:00",
                json.dumps(["gemini-2.5-pro"]), json.dumps({"L1,L2": 0.1}), "stripped", "accept",
                0.9, 0, "[]", json.dumps(prompt_hashes), 2, sig,
            ),
        )
        conn.commit()
        conn.close()

        # Opening with the v3 store migrates (adds artifact_type / retrieval_pins columns).
        store = ReceiptStore(db_path=db, signing_secret=secret)
        assert store.verify_signature("prism-legacy-v2") is True  # v2 signature still valid
        legacy = store.get_receipt("prism-legacy-v2")
        assert legacy["schema_version"] == 2  # stays v2 — not silently upgraded
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


class TestSigningSecretResolution:
    """v0.2.0: refuse the built-in dev key unless explicitly opted in."""

    def test_no_secret_no_env_raises(self, tmp_path, monkeypatch):
        monkeypatch.delenv("PRISM_SIGNING_SECRET", raising=False)
        monkeypatch.delenv("PRISM_DEV", raising=False)
        with pytest.raises(SigningSecretError):
            ReceiptStore(db_path=tmp_path / "r.db")

    def test_prism_dev_allows_dev_key(self, tmp_path, monkeypatch):
        monkeypatch.delenv("PRISM_SIGNING_SECRET", raising=False)
        monkeypatch.setenv("PRISM_DEV", "1")
        ReceiptStore(db_path=tmp_path / "r.db").close()

    def test_explicit_secret_satisfies_without_env(self, tmp_path, monkeypatch):
        monkeypatch.delenv("PRISM_SIGNING_SECRET", raising=False)
        monkeypatch.delenv("PRISM_DEV", raising=False)
        ReceiptStore(db_path=tmp_path / "r.db", signing_secret=b"x").close()

    def test_env_secret_round_trips_signature(self, tmp_path, monkeypatch):
        monkeypatch.delenv("PRISM_DEV", raising=False)
        monkeypatch.setenv("PRISM_SIGNING_SECRET", "prod-secret")
        store = ReceiptStore(db_path=tmp_path / "r.db")
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
        assert store.verify_signature(r.id) is True
        store.close()


class TestStoreLifecycle:
    """v0.3.0: cross-thread safety + context-manager close."""

    def _mk(self, store):
        return store.create_receipt(
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

    def test_usable_from_a_different_thread(self, tmp_path):
        # Constructed on the main thread, used from a worker thread: without
        # check_same_thread=False this raises sqlite3.ProgrammingError.
        store = ReceiptStore(db_path=tmp_path / "t.db", signing_secret=b"s")
        results: list[bool] = []

        def _work() -> None:
            r = self._mk(store)
            results.append(store.verify_signature(r.id))

        t = threading.Thread(target=_work)
        t.start()
        t.join()
        assert results == [True]
        store.close()

    def test_context_manager_closes_connection(self, tmp_path):
        with ReceiptStore(db_path=tmp_path / "c.db", signing_secret=b"s") as store:
            r = self._mk(store)
            assert store.verify_signature(r.id) is True
        # After the context exits the connection is closed.
        with pytest.raises(sqlite3.ProgrammingError):
            store.get_receipt(r.id)
