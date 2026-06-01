"""SQLite receipt store with HMAC signing.

Receipts are the audit trail — every verification produces a signed,
replayable receipt that compensators can reference.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import sqlite3
from datetime import UTC, datetime
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
    signature TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_receipts_timestamp ON receipts(timestamp);
"""


def _generate_receipt_id() -> str:
    return f"prism-{ulid.new().str.lower()}"


def _compute_signature(receipt_data: dict[str, Any], secret: bytes) -> str:
    """HMAC-SHA256 over canonical JSON representation."""
    canonical = json.dumps(receipt_data, sort_keys=True, separators=(",", ":"))
    return hmac.new(secret, canonical.encode(), hashlib.sha256).hexdigest()


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
    ) -> Receipt:
        """Create and store a new receipt."""
        receipt_id = _generate_receipt_id()
        timestamp = datetime.now(UTC)

        # Build canonical data for signing
        sign_data = {
            "id": receipt_id,
            "pre_strip_hash": pre_strip_hash,
            "post_strip_hash": post_strip_hash,
            "timestamp": timestamp.isoformat(),
            "verifier_models": verifier_models,
            "pairwise_rho": pairwise_rho,
            "verdict": verdict,
        }
        signature = _compute_signature(sign_data, self._secret)

        # Store
        self._conn.execute(
            """INSERT INTO receipts
               (id, pre_strip_hash, post_strip_hash, timestamp, verifier_models,
                pairwise_rho, reasoning_visibility_mode, verdict, confidence,
                retryable, lens_results, signature)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
        """Verify the HMAC signature of a stored receipt."""
        data = self.get_receipt(receipt_id)
        if data is None:
            return False

        sign_data = {
            "id": data["id"],
            "pre_strip_hash": data["pre_strip_hash"],
            "post_strip_hash": data["post_strip_hash"],
            "timestamp": data["timestamp"],
            "verifier_models": json.loads(data["verifier_models"]),
            "pairwise_rho": json.loads(data["pairwise_rho"]),
            "verdict": data["verdict"],
        }
        expected = _compute_signature(sign_data, self._secret)
        return hmac.compare_digest(expected, data["signature"])

    def close(self) -> None:
        self._conn.close()
