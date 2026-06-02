"""Tests for v0.4 receipt signing — Ed25519 production default + cross-tool verification."""

from __future__ import annotations

import json

import pytest
from click.testing import CliRunner

from prism.cli.main import cli
from prism.core.types import ReasoningVisibility
from prism.receipts.signing import (
    ALG_ED25519,
    ALG_HMAC,
    DEV_KID,
    Ed25519Backend,
    SigningSecretError,
    generate_keypair,
    resolve_backends,
)
from prism.receipts.store import ReceiptStore, verify_receipt_dict


def _mk(store, verdict="accept"):
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


class TestEd25519Signing:
    def test_ed25519_is_the_default_under_prism_dev(self, tmp_path, monkeypatch):
        monkeypatch.delenv("PRISM_SIGNING_SECRET", raising=False)
        monkeypatch.delenv("PRISM_SIGNING_KEY", raising=False)
        monkeypatch.setenv("PRISM_DEV", "1")
        store = ReceiptStore(db_path=tmp_path / "dev.db")
        r = _mk(store)
        assert r.alg == ALG_ED25519
        assert r.kid.startswith("ed25519-")
        assert store.verify_signature(r.id) is True
        store.close()

    def test_explicit_ed25519_key_round_trips(self, tmp_path):
        priv_pem, _pub, kid = generate_keypair()
        store = ReceiptStore(db_path=tmp_path / "e.db", signing_key=priv_pem)
        r = _mk(store)
        assert r.alg == ALG_ED25519
        assert r.kid == kid
        assert store.verify_signature(r.id) is True
        store.close()

    def test_explicit_hmac_secret_stays_hmac(self, tmp_path):
        # Passing a signing_secret keeps the legacy HMAC backend (kid empty).
        store = ReceiptStore(db_path=tmp_path / "h.db", signing_secret=b"x")
        r = _mk(store)
        assert r.alg == ALG_HMAC
        assert r.kid == ""
        assert store.verify_signature(r.id) is True
        store.close()


class TestCrossToolVerification:
    """The headline: a DIFFERENT tool verifies a prism receipt with prism's PUBLIC key only."""

    def test_public_key_verifies_without_the_secret(self, tmp_path):
        priv_pem, pub_pem, _kid = generate_keypair()
        store = ReceiptStore(db_path=tmp_path / "e.db", signing_key=priv_pem)
        r = _mk(store)
        row = store.get_receipt(r.id)
        store.close()
        # No store, no private key — only the published public key.
        assert verify_receipt_dict(row, public_key_pem=pub_pem) is True

    def test_tampering_breaks_public_key_verification(self, tmp_path):
        priv_pem, pub_pem, _kid = generate_keypair()
        store = ReceiptStore(db_path=tmp_path / "e.db", signing_key=priv_pem)
        r = _mk(store, verdict="accept")
        row = store.get_receipt(r.id)
        store.close()
        row["verdict"] = "refuse"  # flip the verdict
        assert verify_receipt_dict(row, public_key_pem=pub_pem) is False

    def test_wrong_public_key_fails(self, tmp_path):
        priv_pem, _pub, _kid = generate_keypair()
        _other_priv, other_pub, _ = generate_keypair()
        store = ReceiptStore(db_path=tmp_path / "e.db", signing_key=priv_pem)
        r = _mk(store)
        row = store.get_receipt(r.id)
        store.close()
        assert verify_receipt_dict(row, public_key_pem=other_pub) is False

    def test_hmac_receipt_needs_the_secret_not_a_public_key(self, tmp_path):
        store = ReceiptStore(db_path=tmp_path / "h.db", signing_secret=b"shared")
        r = _mk(store)
        row = store.get_receipt(r.id)
        store.close()
        # Right secret verifies; a public key cannot verify an HMAC receipt.
        assert verify_receipt_dict(row, signing_secret=b"shared") is True
        assert verify_receipt_dict(row, signing_secret=b"wrong") is False
        _priv, pub, _ = generate_keypair()
        assert verify_receipt_dict(row, public_key_pem=pub) is False

    def test_negative_zero_verifies_cross_tool_via_public_key(self, tmp_path):
        """Second-hardening regression: a receipt with ``-0.0`` floats verifies on the cross-tool
        public-key path. The signed v5 bytes normalize ``-0.0`` -> ``0.000000000000``, which a
        JS/Go/Rust verifier reproduces with ``toFixed`` / ``%.12f`` / ``{:.12}``. If the signer
        stopped normalizing, the public-key verify (which re-canonicalizes) would desync -> False.
        """
        priv_pem, pub_pem, _kid = generate_keypair()
        store = ReceiptStore(db_path=tmp_path / "e.db", signing_key=priv_pem)
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
        row = store.get_receipt(r.id)
        store.close()
        # Only the published public key — no secret, no database (the role-os cross-tool path).
        assert verify_receipt_dict(row, public_key_pem=pub_pem) is True


class TestVersionAwareAndDowngrade:
    def test_ed25519_store_with_hmac_secret_verifies_legacy_hmac(self, tmp_path):
        # A migrating deployment: Ed25519 signs new receipts, but the retained HMAC secret still
        # verifies legacy HMAC receipts (version-aware — both backends in the verifier registry).
        hmac_store = ReceiptStore(db_path=tmp_path / "legacy.db", signing_secret=b"shared")
        legacy = _mk(hmac_store)
        legacy_row = hmac_store.get_receipt(legacy.id)
        hmac_store.close()

        priv_pem, _pub, _kid = generate_keypair()
        migrated = ReceiptStore(
            db_path=tmp_path / "new.db", signing_secret=b"shared", signing_key=priv_pem
        )
        new = _mk(migrated)
        assert new.alg == ALG_ED25519  # new receipts are Ed25519
        assert migrated.verify_receipt(legacy_row) is True  # legacy HMAC still verifies
        migrated.close()

    def test_ed25519_only_store_cannot_verify_hmac_receipt(self, tmp_path):
        # Honest: without the HMAC secret, an Ed25519-only store cannot verify an HMAC receipt.
        hmac_store = ReceiptStore(db_path=tmp_path / "h.db", signing_secret=b"shared")
        row = hmac_store.get_receipt(_mk(hmac_store).id)
        hmac_store.close()
        priv_pem, _pub, _kid = generate_keypair()
        ed_only = ReceiptStore(db_path=tmp_path / "e.db", signing_key=priv_pem)
        assert ed_only.verify_receipt(row) is False
        ed_only.close()

    def test_downgrade_alg_to_hmac_does_not_verify(self, tmp_path):
        # Flipping a v4 Ed25519 receipt's alg to HMAC must not let it pass (algorithm-confusion).
        priv_pem, _pub, _kid = generate_keypair()
        store = ReceiptStore(
            db_path=tmp_path / "e.db", signing_secret=b"shared", signing_key=priv_pem
        )
        r = _mk(store)
        store._conn.execute("UPDATE receipts SET alg = ? WHERE id = ?", (ALG_HMAC, r.id))
        store._conn.commit()
        # alg now says HMAC, but the signature is Ed25519 — the HMAC verifier rejects it.
        assert store.verify_signature(r.id) is False
        store.close()


class TestResolveBackends:
    def test_no_config_raises(self, tmp_path, monkeypatch):
        monkeypatch.delenv("PRISM_SIGNING_SECRET", raising=False)
        monkeypatch.delenv("PRISM_SIGNING_KEY", raising=False)
        monkeypatch.delenv("PRISM_DEV", raising=False)
        with pytest.raises(SigningSecretError):
            resolve_backends()

    def test_signing_key_env_selects_ed25519(self, tmp_path, monkeypatch):
        priv_pem, _pub, _kid = generate_keypair()
        monkeypatch.delenv("PRISM_SIGNING_SECRET", raising=False)
        monkeypatch.delenv("PRISM_DEV", raising=False)
        monkeypatch.setenv("PRISM_SIGNING_KEY", priv_pem)
        active, verifiers = resolve_backends()
        assert isinstance(active, Ed25519Backend)
        assert ALG_ED25519 in verifiers

    def test_bad_signing_key_raises(self):
        with pytest.raises(SigningSecretError):
            resolve_backends(signing_key="not a pem and not a path")


class TestSigningCli:
    def test_keygen_emits_keypair(self):
        result = CliRunner().invoke(cli, ["keygen"])
        assert result.exit_code == 0
        out = json.loads(result.output)
        assert "BEGIN PRIVATE KEY" in out["private_key"]
        assert "BEGIN PUBLIC KEY" in out["public_key"]
        assert out["kid"].startswith("ed25519-")

    def test_keygen_writes_file(self, tmp_path):
        keyfile = tmp_path / "prism.pem"
        result = CliRunner().invoke(cli, ["keygen", "--out", str(keyfile)])
        assert result.exit_code == 0
        assert keyfile.is_file()
        assert "BEGIN PRIVATE KEY" in keyfile.read_text()

    def test_pubkey_prints_configured_key(self, tmp_path, monkeypatch):
        keyfile = tmp_path / "k.pem"
        CliRunner().invoke(cli, ["keygen", "--out", str(keyfile)])
        monkeypatch.delenv("PRISM_SIGNING_SECRET", raising=False)
        monkeypatch.delenv("PRISM_DEV", raising=False)
        monkeypatch.setenv("PRISM_SIGNING_KEY", str(keyfile))
        result = CliRunner().invoke(cli, ["pubkey"])
        assert result.exit_code == 0
        out = json.loads(result.output)
        assert out["alg"] == ALG_ED25519
        assert "BEGIN PUBLIC KEY" in out["public_key"]

    def test_pubkey_refuses_for_hmac(self, tmp_path, monkeypatch):
        monkeypatch.delenv("PRISM_SIGNING_KEY", raising=False)
        monkeypatch.delenv("PRISM_DEV", raising=False)
        monkeypatch.setenv("PRISM_SIGNING_SECRET", "legacy")
        result = CliRunner().invoke(cli, ["pubkey"])
        assert result.exit_code == 1
        assert "no public key" in result.output.lower() or "HMAC" in result.output

    def test_verify_receipt_with_public_key(self, tmp_path):
        priv_pem, pub_pem, _kid = generate_keypair()
        keyfile = tmp_path / "priv.pem"
        keyfile.write_text(priv_pem)
        pubfile = tmp_path / "pub.pem"
        pubfile.write_text(pub_pem)
        store = ReceiptStore(db_path=tmp_path / "e.db", signing_key=priv_pem)
        row = store.get_receipt(_mk(store).id)
        store.close()
        receipt_file = tmp_path / "receipt.json"
        receipt_file.write_text(json.dumps(row, default=str))

        result = CliRunner().invoke(
            cli, ["verify-receipt", str(receipt_file), "--public-key", str(pubfile)]
        )
        assert result.exit_code == 0
        assert json.loads(result.output)["signature_valid"] is True

    def test_verify_receipt_tampered_exits_1(self, tmp_path):
        priv_pem, pub_pem, _kid = generate_keypair()
        pubfile = tmp_path / "pub.pem"
        pubfile.write_text(pub_pem)
        store = ReceiptStore(db_path=tmp_path / "e.db", signing_key=priv_pem)
        row = store.get_receipt(_mk(store, verdict="accept").id)
        store.close()
        row["verdict"] = "refuse"
        receipt_file = tmp_path / "receipt.json"
        receipt_file.write_text(json.dumps(row, default=str))

        result = CliRunner().invoke(
            cli, ["verify-receipt", str(receipt_file), "--public-key", str(pubfile)]
        )
        assert result.exit_code == 1
        assert json.loads(result.output)["signature_valid"] is False


class TestDevKidRejectedInProduction:
    """RCPT-A-003: the well-known dev kid is forgeable, so a production verifier refuses it.

    The dev Ed25519 seed is public source — anyone can derive its key + ``kid`` and forge a
    receipt bearing ``DEV_KID``. Signing with it is gated behind PRISM_DEV=1; the verify side
    must REFUSE a dev-kid receipt unless PRISM_DEV=1 too, while genuine prism->prism dev
    round-trips keep working under PRISM_DEV=1.
    """

    def _dev_receipt_row(self, tmp_path, monkeypatch):
        monkeypatch.delenv("PRISM_SIGNING_SECRET", raising=False)
        monkeypatch.delenv("PRISM_SIGNING_KEY", raising=False)
        monkeypatch.setenv("PRISM_DEV", "1")  # zero-config dev signs with the dev Ed25519 key
        store = ReceiptStore(db_path=tmp_path / "dev.db")
        r = _mk(store)
        assert r.kid == DEV_KID  # the dev seed produces the well-known kid
        row = store.get_receipt(r.id)
        store.close()
        return row

    def test_store_refuses_dev_kid_receipt_without_prism_dev(self, tmp_path, monkeypatch):
        row = self._dev_receipt_row(tmp_path, monkeypatch)
        # Now stand up a PRODUCTION verifier (real key, PRISM_DEV unset).
        monkeypatch.delenv("PRISM_DEV", raising=False)
        priv_pem, _pub, _kid = generate_keypair()
        prod = ReceiptStore(db_path=tmp_path / "prod.db", signing_key=priv_pem)
        # Even though the dev backend isn't registered here, the kid guard refuses it outright.
        assert prod.verify_receipt(row) is False
        prod.close()

    def test_public_key_path_refuses_dev_kid_without_prism_dev(self, tmp_path, monkeypatch):
        row = self._dev_receipt_row(tmp_path, monkeypatch)
        dev_pub = Ed25519Backend.dev().public_key_pem()  # the (public) dev verifying key
        monkeypatch.delenv("PRISM_DEV", raising=False)
        # Production cross-tool verify with the genuine dev public key STILL refuses (forgeable).
        assert verify_receipt_dict(row, public_key_pem=dev_pub) is False

    def test_dev_kid_receipt_accepted_only_under_prism_dev(self, tmp_path, monkeypatch):
        row = self._dev_receipt_row(tmp_path, monkeypatch)
        dev_pub = Ed25519Backend.dev().public_key_pem()
        # Same signature, same public key — but with PRISM_DEV=1 the dev round-trip verifies.
        monkeypatch.setenv("PRISM_DEV", "1")
        assert verify_receipt_dict(row, public_key_pem=dev_pub) is True


class TestCrossVersionDispatch:
    """RCPT-A-001: a hand-built v4 receipt with a v4 HMAC signature still verifies after v5."""

    def test_v4_receipt_with_v4_signature_verifies_in_v5_store(self, tmp_path):
        from prism.receipts.store import _build_sign_data, _compute_signature

        secret = b"shared-cross-version"
        # Build a v4 signed field-set and sign it with the v4 canonicalizer (Python json defaults).
        sign = _build_sign_data(
            schema_version=4,
            receipt_id="prism-v4-handbuilt",
            pre_strip_hash="aa",
            post_strip_hash="bb",
            timestamp="2026-05-20T00:00:00+00:00",
            verifier_models=["gemini-2.5-pro"],
            pairwise_rho={"L1,L2": 0.1},
            verdict="accept",
            reasoning_visibility_mode="stripped",
            confidence=0.9,
            retryable=False,
            lens_results_json="[]",
            lens_prompt_hashes={"contract": "abc123"},
            alg=ALG_HMAC,
            kid="",
        )
        sig = _compute_signature(sign, secret)  # HMAC over the v4 canonical bytes
        row = {
            "id": "prism-v4-handbuilt",
            "pre_strip_hash": "aa",
            "post_strip_hash": "bb",
            "timestamp": "2026-05-20T00:00:00+00:00",
            "verifier_models": json.dumps(["gemini-2.5-pro"]),
            "pairwise_rho": json.dumps({"L1,L2": 0.1}),
            "reasoning_visibility_mode": "stripped",
            "verdict": "accept",
            "confidence": 0.9,
            "retryable": 0,
            "lens_results": "[]",
            "lens_prompt_hashes": json.dumps({"contract": "abc123"}),
            "artifact_type": "code",
            "retrieval_pins": "[]",
            "alg": ALG_HMAC,
            "kid": "",
            "schema_version": 4,
            "signature": sig,
        }
        # A v5-default store (it would SIGN new receipts at v5) still verifies this v4 receipt,
        # because verification dispatches the canonicalizer on the receipt's own schema_version.
        store = ReceiptStore(db_path=tmp_path / "mix.db", signing_secret=secret)
        assert store.verify_receipt(row) is True
        # Flipping schema_version to 5 (without re-signing) must NOT verify — the v5 canonicalizer
        # produces different bytes, proving the dispatch is real and not a no-op.
        row_wrong = {**row, "schema_version": 5}
        assert store.verify_receipt(row_wrong) is False
        store.close()
