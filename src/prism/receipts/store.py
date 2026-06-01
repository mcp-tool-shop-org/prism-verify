"""SQLite receipt store with HMAC signing.

Receipts are the audit trail — every verification produces a signed,
replayable receipt that compensators can reference.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import ulid

from prism.core.types import (
    ReasoningVisibility,
    Receipt,
)

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
    schema_version INTEGER NOT NULL DEFAULT 2,
    signature TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_receipts_timestamp ON receipts(timestamp);
"""

# Current signed-receipt schema version. v1 (legacy) signed only the 7 base fields;
# v2 also signs reasoning_visibility_mode, confidence, retryable, a hash of lens_results,
# and lens_prompt_hashes (the PIN) — plus the version itself, to block downgrade attacks.
CURRENT_SCHEMA_VERSION = 2


def _generate_receipt_id() -> str:
    return f"prism-{ulid.new().str.lower()}"


def _compute_signature(receipt_data: dict[str, Any], secret: bytes) -> str:
    """HMAC-SHA256 over canonical JSON representation."""
    canonical = json.dumps(receipt_data, sort_keys=True, separators=(",", ":"))
    return hmac.new(secret, canonical.encode(), hashlib.sha256).hexdigest()


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
) -> dict[str, Any]:
    """Build the exact dict that is HMAC-signed, for a given schema version.

    v1 (legacy) signs only the 7 base fields, so receipts written before the v0.2.0
    PIN work still verify. v2 additionally signs the reasoning-visibility mode, the
    caller-actionable confidence/retryable outputs, a hash of the lens results, the lens
    prompt hashes (the PIN), and the version itself (so a tamperer cannot downgrade a v2
    receipt to v1 to strip the extra protected fields).
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
    return base


class ReceiptStore:
    """SQLite-backed receipt store with HMAC signing."""

    def __init__(
        self,
        db_path: Path | None = None,
        signing_secret: bytes | None = None,
    ) -> None:
        self._db_path = db_path or DEFAULT_DB_PATH
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._secret = signing_secret or b"prism-dev-secret"
        self._conn = sqlite3.connect(str(self._db_path))
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(_SCHEMA)
        self._migrate()

    def _migrate(self) -> None:
        """Bring an older receipts.db up to the current schema (idempotent).

        v0.1 databases predate the lens_prompt_hashes / schema_version columns, and a
        bare CREATE TABLE IF NOT EXISTS will not add them, so we ALTER in any that are
        missing. Columns are added with constant DEFAULTs (SQLite forbids a bare NOT NULL
        ADD COLUMN on a populated table); legacy rows backfill schema_version=1 so their
        original 7-field signatures still verify.
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
    ) -> Receipt:
        """Create and store a new receipt (always at the current schema version)."""
        receipt_id = _generate_receipt_id()
        timestamp = datetime.now(UTC)
        prompt_hashes = lens_prompt_hashes or {}

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
        )
        signature = _compute_signature(sign_data, self._secret)

        self._conn.execute(
            """INSERT INTO receipts
               (id, pre_strip_hash, post_strip_hash, timestamp, verifier_models,
                pairwise_rho, reasoning_visibility_mode, verdict, confidence,
                retryable, lens_results, lens_prompt_hashes, schema_version, signature)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
            schema_version=CURRENT_SCHEMA_VERSION,
            signature=signature,
            replayable=True,
        )

    def get_receipt(self, receipt_id: str) -> dict[str, Any] | None:
        """Retrieve a receipt by ID."""
        cursor = self._conn.execute(
            "SELECT * FROM receipts WHERE id = ?", (receipt_id,)
        )
        row = cursor.fetchone()
        if row is None:
            return None

        columns = [desc[0] for desc in cursor.description]
        return dict(zip(columns, row))

    def verify_signature(self, receipt_id: str) -> bool:
        """Verify the HMAC signature of a stored receipt.

        Reconstructs the signed payload at the receipt's own schema version, so legacy
        v1 receipts (signed over the original 7 fields) still verify after a v2 migration.
        """
        data = self.get_receipt(receipt_id)
        if data is None:
            return False

        schema_version = int(data.get("schema_version") or 1)
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
        )
        expected = _compute_signature(sign_data, self._secret)
        return hmac.compare_digest(expected, data["signature"])

    def delete_receipt(self, receipt_id: str) -> bool:
        """Delete a single receipt by ID; returns True if a row was removed.

        Named compensator for the receipt INSERT (design/03-compensators.md). Terminal:
        a deleted receipt cannot be recovered — deletion is a GDPR/retention escape hatch,
        not an undo for a wrong verdict.
        """
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
        cur = self._conn.execute("DELETE FROM receipts WHERE timestamp < ?", (cutoff,))
        self._conn.commit()
        return cur.rowcount

    def close(self) -> None:
        self._conn.close()
