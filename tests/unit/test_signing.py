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
