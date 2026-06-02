"""SQLite receipt store with versioned signatures (HMAC legacy + Ed25519 default, v0.4).

Receipts are the audit trail — every verification produces a signed, replayable receipt that
compensators can reference. v0.4 makes Ed25519 the production default so a DIFFERENT tool can
verify a receipt with prism's PUBLIC key (no shared secret); each receipt records its ``alg`` and
``kid`` and is verified against the algorithm it was signed with, so legacy HMAC receipts keep
verifying after the migration (version-aware — see ``receipts/signing.py`` + ``design/05``).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import sqlite3
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import ulid
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from prism.core.types import (
    ReasoningVisibility,
    Receipt,
)
from prism.receipts.signing import (
    ALG_HMAC,
    Ed25519Backend,
    SigningBackend,
    SigningSecretError,
    resolve_backends,
)

__all__ = [
    "ReceiptStore",
    "SigningSecretError",
    "CURRENT_SCHEMA_VERSION",
]

DEFAULT_DB_PATH = Path.home() / ".prism" / "receipts.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS receipts (
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
    artifact_type TEXT NOT NULL DEFAULT 'code',
    retrieval_pins TEXT NOT NULL DEFAULT '[]',
    alg TEXT NOT NULL DEFAULT 'HMAC-SHA256',
    kid TEXT NOT NULL DEFAULT '',
    schema_version INTEGER NOT NULL DEFAULT 4,
    signature TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_receipts_timestamp ON receipts(timestamp);
"""

# Current signed-receipt schema version. v1 (legacy) signed only the 7 base fields; v2 also
# signs reasoning_visibility_mode, confidence, retryable, a hash of lens_results, and
# lens_prompt_hashes (the PIN); v3 (citations) also signs artifact_type and a hash of
# retrieval_pins; v4 (asymmetric receipts) also signs alg + kid (the signing algorithm and key id)
# — plus the version itself, to block downgrade/algorithm-confusion attacks. Each version signs
# only its own field-set, so legacy receipts still verify after a migration.
CURRENT_SCHEMA_VERSION = 4


def _generate_receipt_id() -> str:
    return f"prism-{ulid.new().str.lower()}"


def _canonical(receipt_data: dict[str, Any]) -> bytes:
    """The exact canonical byte representation that is signed/verified."""
    return json.dumps(receipt_data, sort_keys=True, separators=(",", ":")).encode()


def _compute_signature(receipt_data: dict[str, Any], secret: bytes) -> str:
    """HMAC-SHA256 over the canonical JSON representation (the legacy/HMAC signature)."""
    return hmac.new(secret, _canonical(receipt_data), hashlib.sha256).hexdigest()


def _build_sign_data(
    *,
    schema_version: int,
    receipt_id: str,
    pre_strip_hash: str,
    post_strip_hash: str,
    timestamp: str,
    verifier_models: list[str],
    pairwise_rho: dict[str, float],
    verdict: str,
    reasoning_visibility_mode: str,
    confidence: float,
    retryable: bool,
    lens_results_json: str,
    lens_prompt_hashes: dict[str, str],
    artifact_type: str = "code",
    retrieval_pins: list[dict[str, str]] | None = None,
    alg: str = ALG_HMAC,
    kid: str = "",
) -> dict[str, Any]:
    """Build the exact dict that is signed, for a given schema version.

    v1 (legacy) signs only the 7 base fields, so receipts written before the v0.2.0 PIN work
    still verify. v2 additionally signs the reasoning-visibility mode, the caller-actionable
    confidence/retryable outputs, a hash of the lens results, the lens prompt hashes (the PIN),
    and the version itself (so a tamperer cannot downgrade a receipt to strip protected fields).
    v3 adds artifact_type + a hash of retrieval_pins. v4 adds alg + kid (the signing algorithm
    and key id) so a verifier dispatches on — and cannot be tricked about — the algorithm.
    """
    base: dict[str, Any] = {
        "id": receipt_id,
        "pre_strip_hash": pre_strip_hash,
        "post_strip_hash": post_strip_hash,
        "timestamp": timestamp,
        "verifier_models": verifier_models,
        "pairwise_rho": pairwise_rho,
        "verdict": verdict,
    }
    if schema_version < 2:
        return base
    base.update(
        {
            "reasoning_visibility_mode": reasoning_visibility_mode,
            "confidence": float(confidence),
            "retryable": bool(retryable),
            "lens_results_hash": hashlib.sha256(lens_results_json.encode()).hexdigest(),
            "lens_prompt_hashes": lens_prompt_hashes,
            "schema_version": schema_version,
        }
    )
    if schema_version < 3:
        return base
    base.update(
        {
            "artifact_type": artifact_type,
            "retrieval_pins_hash": hashlib.sha256(
                json.dumps(retrieval_pins or [], sort_keys=True).encode()
            ).hexdigest(),
        }
    )
    if schema_version < 4:
        return base
    base.update({"alg": alg, "kid": kid})
    return base


class ReceiptStore:
    """SQLite-backed receipt store with versioned (HMAC + Ed25519) signatures."""

    def __init__(
        self,
        db_path: Path | None = None,
        signing_secret: bytes | None = None,
        signing_key: str | Ed25519PrivateKey | Ed25519Backend | None = None,
    ) -> None:
        # Resolve the active signing backend (signs new receipts) + a verifier registry keyed by
        # algorithm (verifies receipts of any alg we hold key material for). Ed25519 is the v0.4
        # production default; HMAC is retained for legacy + explicit opt-in.
        self._signer, self._verifiers = resolve_backends(signing_secret, signing_key)
        self._db_path = db_path or DEFAULT_DB_PATH
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        # prism runs on an asyncio loop that may live on a different thread than the one that
        # constructed the store (e.g. embedded in a threaded host); the default
        # check_same_thread=True would then raise on first cross-thread use. Open with
        # check_same_thread=False and serialize every access through a reentrant lock —
        # safe for a shared handle, without per-call connection churn.
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(_SCHEMA)
        self._migrate()

    def _migrate(self) -> None:
        """Bring an older receipts.db up to the current schema (idempotent).

        Older databases predate the lens_prompt_hashes / schema_version / artifact_type /
        retrieval_pins / alg / kid columns, and a bare CREATE TABLE IF NOT EXISTS will not add
        them, so we ALTER in any that are missing. Columns are added with constant DEFAULTs
        (SQLite forbids a bare NOT NULL ADD COLUMN on a populated table); legacy rows backfill
        schema_version=1 and alg='HMAC-SHA256' so their original signatures still verify.
        """
        cur = self._conn.execute("PRAGMA table_info(receipts)")
        columns = {row[1] for row in cur.fetchall()}
        if "schema_version" not in columns:
            self._conn.execute(
                "ALTER TABLE receipts ADD COLUMN schema_version INTEGER NOT NULL DEFAULT 1"
            )
        if "lens_prompt_hashes" not in columns:
            self._conn.execute(
                "ALTER TABLE receipts ADD COLUMN lens_prompt_hashes TEXT NOT NULL DEFAULT '{}'"
            )
        if "artifact_type" not in columns:
            self._conn.execute(
                "ALTER TABLE receipts ADD COLUMN artifact_type TEXT NOT NULL DEFAULT 'code'"
            )
        if "retrieval_pins" not in columns:
            self._conn.execute(
                "ALTER TABLE receipts ADD COLUMN retrieval_pins TEXT NOT NULL DEFAULT '[]'"
            )
        if "alg" not in columns:
            self._conn.execute(
                "ALTER TABLE receipts ADD COLUMN alg TEXT NOT NULL DEFAULT 'HMAC-SHA256'"
            )
        if "kid" not in columns:
            self._conn.execute("ALTER TABLE receipts ADD COLUMN kid TEXT NOT NULL DEFAULT ''")
        self._conn.execute(f"PRAGMA user_version = {CURRENT_SCHEMA_VERSION}")
        self._conn.commit()

    def create_receipt(
        self,
        pre_strip_hash: str,
        post_strip_hash: str,
        verifier_models: list[str],
        pairwise_rho: dict[str, float],
        reasoning_visibility_mode: ReasoningVisibility,
        verdict: str,
        confidence: float,
        retryable: bool,
        lens_results_json: str,
        lens_prompt_hashes: dict[str, str] | None = None,
        artifact_type: str = "code",
        retrieval_pins: list[dict[str, str]] | None = None,
    ) -> Receipt:
        """Create and store a new receipt (always at the current schema version)."""
        receipt_id = _generate_receipt_id()
        timestamp = datetime.now(UTC)
        prompt_hashes = lens_prompt_hashes or {}
        pins = retrieval_pins or []
        alg = self._signer.alg
        kid = self._signer.kid

        sign_data = _build_sign_data(
            schema_version=CURRENT_SCHEMA_VERSION,
            receipt_id=receipt_id,
            pre_strip_hash=pre_strip_hash,
            post_strip_hash=post_strip_hash,
            timestamp=timestamp.isoformat(),
            verifier_models=verifier_models,
            pairwise_rho=pairwise_rho,
            verdict=verdict,
            reasoning_visibility_mode=reasoning_visibility_mode.value,
            confidence=confidence,
            retryable=retryable,
            lens_results_json=lens_results_json,
            lens_prompt_hashes=prompt_hashes,
            artifact_type=artifact_type,
            retrieval_pins=pins,
            alg=alg,
            kid=kid,
        )
        signature = self._signer.sign(_canonical(sign_data))

        with self._lock:
            self._conn.execute(
                """INSERT INTO receipts
                   (id, pre_strip_hash, post_strip_hash, timestamp, verifier_models,
                    pairwise_rho, reasoning_visibility_mode, verdict, confidence,
                    retryable, lens_results, lens_prompt_hashes, artifact_type,
                    retrieval_pins, alg, kid, schema_version, signature)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    receipt_id,
                    pre_strip_hash,
                    post_strip_hash,
                    timestamp.isoformat(),
                    json.dumps(verifier_models),
                    json.dumps(pairwise_rho),
                    reasoning_visibility_mode.value,
                    verdict,
                    confidence,
                    int(retryable),
                    lens_results_json,
                    json.dumps(prompt_hashes),
                    artifact_type,
                    json.dumps(pins),
                    alg,
                    kid,
                    CURRENT_SCHEMA_VERSION,
                    signature,
                ),
            )
            self._conn.commit()

        return Receipt(
            id=receipt_id,
            pre_strip_hash=pre_strip_hash,
            post_strip_hash=post_strip_hash,
            timestamp=timestamp,
            verifier_models=verifier_models,
            pairwise_rho=pairwise_rho,
            reasoning_visibility_mode=reasoning_visibility_mode,
            lens_prompt_hashes=prompt_hashes,
            artifact_type=artifact_type,
            retrieval_pins=pins,
            alg=alg,
            kid=kid,
            schema_version=CURRENT_SCHEMA_VERSION,
            signature=signature,
            replayable=True,
        )

    def get_receipt(self, receipt_id: str) -> dict[str, Any] | None:
        """Retrieve a receipt by ID."""
        with self._lock:
            cursor = self._conn.execute(
                "SELECT * FROM receipts WHERE id = ?", (receipt_id,)
            )
            row = cursor.fetchone()
            if row is None:
                return None
            columns = [desc[0] for desc in cursor.description]
            return dict(zip(columns, row))

    def verify_signature(self, receipt_id: str) -> bool:
        """Verify the signature of a stored receipt.

        Reconstructs the signed payload at the receipt's own schema version and dispatches to the
        backend matching the receipt's recorded ``alg`` (whitelisted — a receipt can never pick a
        verifier path we do not hold a key for). Legacy v1/v2/v3 receipts (signed over their own
        field-set, alg defaulting to HMAC) still verify after a v4 migration.
        """
        data = self.get_receipt(receipt_id)
        if data is None:
            return False
        return self._verify_row(data)

    def verify_receipt(self, receipt: dict[str, Any]) -> bool:
        """Verify a STANDALONE receipt dict (e.g. ``prism replay`` output) against this store's
        keys — without it having to be in this database. Dispatches on the receipt's ``alg``."""
        return self._verify_row(receipt)

    def _verify_row(self, data: dict[str, Any]) -> bool:
        schema_version = int(data.get("schema_version") or 1)
        alg = data.get("alg") or ALG_HMAC
        backend = self._verifiers.get(alg)
        if backend is None:
            # We hold no key for this algorithm — cannot verify (e.g. an Ed25519-only store asked
            # to verify a legacy HMAC receipt without the HMAC secret).
            return False
        sign_data = _build_sign_data(
            schema_version=schema_version,
            receipt_id=data["id"],
            pre_strip_hash=data["pre_strip_hash"],
            post_strip_hash=data["post_strip_hash"],
            timestamp=data["timestamp"],
            verifier_models=json.loads(data["verifier_models"]),
            pairwise_rho=json.loads(data["pairwise_rho"]),
            verdict=data["verdict"],
            reasoning_visibility_mode=data["reasoning_visibility_mode"],
            confidence=data["confidence"],
            retryable=bool(data["retryable"]),
            lens_results_json=data["lens_results"],
            lens_prompt_hashes=json.loads(data.get("lens_prompt_hashes") or "{}"),
            artifact_type=data.get("artifact_type", "code"),
            retrieval_pins=json.loads(data.get("retrieval_pins") or "[]"),
            alg=alg,
            kid=data.get("kid", ""),
        )
        return backend.verify(_canonical(sign_data), data["signature"])

    def delete_receipt(self, receipt_id: str) -> bool:
        """Delete a single receipt by ID; returns True if a row was removed.

        Named compensator for the receipt INSERT (design/03-compensators.md). Terminal:
        a deleted receipt cannot be recovered — deletion is a GDPR/retention escape hatch,
        not an undo for a wrong verdict.
        """
        with self._lock:
            cur = self._conn.execute("DELETE FROM receipts WHERE id = ?", (receipt_id,))
            self._conn.commit()
            return cur.rowcount > 0

    def prune(self, older_than: timedelta) -> int:
        """Delete receipts older than ``older_than``; returns the number removed.

        Prunes on the signed UTC ``timestamp`` column (not the local ``created_at``), so
        the cutoff is timezone-consistent. Irreversible — export before pruning if the
        audit trail matters.
        """
        cutoff = (datetime.now(UTC) - older_than).isoformat()
        with self._lock:
            cur = self._conn.execute("DELETE FROM receipts WHERE timestamp < ?", (cutoff,))
            self._conn.commit()
            return cur.rowcount

    def __enter__(self) -> ReceiptStore:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        with self._lock:
            self._conn.close()


def verify_receipt_dict(
    receipt: dict[str, Any],
    *,
    signing_secret: bytes | None = None,
    public_key_pem: str | None = None,
) -> bool:
    """Verify a STANDALONE receipt dict (e.g. exported JSON) without a database.

    The cross-tool path: an Ed25519 receipt verifies with only ``public_key_pem`` — no shared
    secret, no prism database — which is how role-os (a different tool) confirms a prism receipt.
    An HMAC receipt needs ``signing_secret``. Returns False if no key for the receipt's ``alg``
    is supplied.
    """
    alg = receipt.get("alg") or ALG_HMAC
    backend: SigningBackend | None = None
    if alg == ALG_HMAC and signing_secret is not None:
        from prism.receipts.signing import HmacBackend

        backend = HmacBackend(signing_secret)
    elif alg != ALG_HMAC and public_key_pem is not None:
        backend = Ed25519Backend.from_public_pem(public_key_pem)
    if backend is None:
        return False

    schema_version = int(receipt.get("schema_version") or 1)
    verifier_models = receipt["verifier_models"]
    if isinstance(verifier_models, str):
        verifier_models = json.loads(verifier_models)
    pairwise_rho = receipt["pairwise_rho"]
    if isinstance(pairwise_rho, str):
        pairwise_rho = json.loads(pairwise_rho)
    lens_prompt_hashes = receipt.get("lens_prompt_hashes") or {}
    if isinstance(lens_prompt_hashes, str):
        lens_prompt_hashes = json.loads(lens_prompt_hashes)
    retrieval_pins = receipt.get("retrieval_pins") or []
    if isinstance(retrieval_pins, str):
        retrieval_pins = json.loads(retrieval_pins)
    lens_results = receipt.get("lens_results", "[]")
    if not isinstance(lens_results, str):
        lens_results = json.dumps(lens_results, default=str)

    sign_data = _build_sign_data(
        schema_version=schema_version,
        receipt_id=receipt["id"],
        pre_strip_hash=receipt["pre_strip_hash"],
        post_strip_hash=receipt["post_strip_hash"],
        timestamp=receipt["timestamp"],
        verifier_models=verifier_models,
        pairwise_rho=pairwise_rho,
        verdict=receipt["verdict"],
        reasoning_visibility_mode=receipt["reasoning_visibility_mode"],
        confidence=receipt["confidence"],
        retryable=bool(receipt["retryable"]),
        lens_results_json=lens_results,
        lens_prompt_hashes=lens_prompt_hashes,
        artifact_type=receipt.get("artifact_type", "code"),
        retrieval_pins=retrieval_pins,
        alg=alg,
        kid=receipt.get("kid", ""),
    )
    return backend.verify(_canonical(sign_data), receipt["signature"])
