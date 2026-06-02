"""SQLite receipt store with versioned signatures (HMAC legacy + Ed25519 default, v0.4).

Receipts are the audit trail — every verification produces a signed, replayable receipt that
compensators can reference. v0.4 makes Ed25519 the production default so a DIFFERENT tool can
verify a receipt with prism's PUBLIC key (no shared secret); each receipt records its ``alg`` and
``kid`` and is verified against the algorithm it was signed with, so legacy HMAC receipts keep
verifying after the migration (version-aware — see ``receipts/signing.py`` + ``design/05``).

Canonical signed bytes (versioned — see ``_canonical``/``_canonical_v4``/``_canonical_v5``)
---------------------------------------------------------------------------------------------
The signature is computed over a CANONICAL byte serialization of the receipt's signed field-set.
Verification reproduces those exact bytes; a single differing byte fails the check. Because the
v0.4 headline is THIRD-PARTY verifiability (role-os, or any non-CPython tool, reproduces the bytes
from only the public key), the canonical format is versioned and dispatched on the receipt's
stored ``schema_version`` so already-issued receipts keep verifying:

* **schema_version <= 4** → ``_canonical_v4``: ``json.dumps(sort_keys=True, separators=(",",":"))``
  with Python defaults (``ensure_ascii=True`` → ``\\uXXXX`` escapes, Python float ``repr``). This is
  the EXACT pre-v5 behavior, retained byte-for-byte so legacy v1/v2/v3/v4 receipts still verify.
  It is Python-``json``-specific and is NOT recommended for cross-tool reproduction.

* **schema_version == 5** → ``_canonical_v5``: an RFC 8785 (JCS)-style profile a non-Python tool
  can reproduce. NEW receipts are signed at v5. The exact, language-agnostic byte rules are:

  1. **Object keys** are sorted ascending by Unicode code point (UTF-16 code unit order, which for
     the BMP-only keys prism emits equals code-point order), recursively at every nesting level.
  2. **No insignificant whitespace.** Separators are exactly ``,`` between elements and ``:``
     between a key and its value.
  3. **Strings** use standard JSON escaping (RFC 8259 §7): ``"``, ``\\``, and the control chars
     U+0000–U+001F are escaped (``\\n``, ``\\t``, ``\\r``, ``\\b``, ``\\f``, else ``\\u00XX``); ALL
     other characters — including non-ASCII — are emitted as literal UTF-8 (``ensure_ascii=False``,
     NOT ``\\uXXXX``). The whole document is UTF-8 with no BOM.
  4. **Integers** (e.g. ``schema_version``) are emitted as their shortest decimal, no exponent,
     no fraction (``5``, not ``5.0``). **Booleans** are ``true``/``false`` (NOT ``1``/``0``).
  5. **Floats** (only ``confidence`` and each ``pairwise_rho`` value, all in ``[0, 1]``) are
     emitted by this PRECISE rule, chosen for trivial cross-language reproduction:
       a. reject non-finite values (NaN / ±Infinity) — they are not signable (ties RCPT-A-002);
       b. normalize signed zero — IEEE-754 ``-0.0`` is collapsed to ``+0.0`` BEFORE formatting, so
          it renders ``0.000000000000``. (Python's Decimal/repr render ``-0.0`` as
          ``-0.000000000000`` while JS ``(-0).toFixed(12)`` yields ``0.000000000000``; SQLite's REAL
          column also drops the sign bit, so a ``-0.0`` would sign one way and read back the other.
          Normalizing first closes both the cross-tool and self-verify divergences.)
       c. round the IEEE-754 double to **12 fractional decimal places** using **round-half-to-even**
          (banker's rounding — IEEE 754 ``roundTiesToEven``, the default in JS/Go/Rust/Java);
       d. emit a **plain decimal with EXACTLY 12 digits after the point** — never scientific
          notation, never trailing-zero stripping. E.g. ``0.9`` → ``0.900000000000``; ``1/3`` →
          ``0.333333333333``; ``0.30000000000000004`` → ``0.300000000000``; ``1.0`` →
          ``1.000000000000``; ``0.0`` (and ``-0.0``) → ``0.000000000000``.
     A third party reproduces (d) directly: JS ``x.toFixed(12)``, Go ``fmt.Sprintf("%.12f", x)``,
     Rust ``format!("{:.12}", x)``, Python ``format(x, ".12f")`` — all agree for x in ``[0, 1]``
     once signed zero is normalized per (b).
  6. ``null`` is the literal ``null`` (prism does not currently emit it in signed fields).

  The signed payload is itself valid strict JSON (parseable with ``allow_nan=False``), so a
  consumer can both verify the signature AND parse the receipt with a standards-compliant reader.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import math
import sqlite3
import threading
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_EVEN, Decimal, localcontext
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
    DEV_KID,
    Ed25519Backend,
    SigningBackend,
    SigningSecretError,
    prism_dev_enabled,
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
# — plus the version itself, to block downgrade/algorithm-confusion attacks. v5 keeps the v4
# field-set but switches the CANONICAL BYTE FORMAT to an RFC 8785-style profile (UTF-8, no \uXXXX
# escapes, fixed-precision floats) that a non-Python tool can reproduce — the cross-tool verify
# promise (see the module docstring). Each version signs its own field-set with its own
# canonicalizer, and verification dispatches on the receipt's stored schema_version, so legacy
# v1–v4 receipts still verify after the migration.
CURRENT_SCHEMA_VERSION = 5


def _generate_receipt_id() -> str:
    return f"prism-{ulid.new().str.lower()}"


# Number of fractional decimal places the v5 canonicalizer rounds floats to (round-half-to-even),
# then emits with EXACTLY this many digits after the point. confidence/pairwise_rho are in [0, 1],
# so this never needs scientific notation. See the module docstring for the full byte rule.
_V5_FLOAT_PLACES = 12
_V5_QUANTUM = Decimal(1).scaleb(-_V5_FLOAT_PLACES)  # Decimal("1E-12")
# Fixed precision for the v5 quantize, applied in a LOCAL context so the canonical bytes never
# depend on the host's ambient Decimal precision (determinism is the cross-tool promise) and
# quantize can never raise InvalidOperation on the verify path. A [0, 1]-with-12-places result
# is at most 13 significant digits; 34 (IEEE 754 decimal128) is ample headroom.
_V5_DECIMAL_PREC = 34


def _canonical_v4(receipt_data: dict[str, Any]) -> bytes:
    """schema_version <= 4 canonical bytes — Python-``json``-specific (ensure_ascii=True, Python
    float repr). Retained BYTE-FOR-BYTE so already-issued v1–v4 receipts keep verifying. Do not
    change: any tweak invalidates every signature ever written at v4 or below."""
    return json.dumps(receipt_data, sort_keys=True, separators=(",", ":")).encode()


def _v5_number(value: float) -> str:
    """Format a float per the v5 rule: reject non-finite, round-half-to-even to 12 fractional
    places, emit a plain decimal with EXACTLY 12 digits after the point (no exponent, no stripping).

    Reproducible in any language: JS ``x.toFixed(12)`` / Go ``%.12f`` / Rust ``{:.12}`` agree with
    this for x in ``[0, 1]`` once signed zero is normalized (so ``-0.0`` → ``0.000000000000``,
    matching ``toFixed``). ``Decimal(value)`` takes the exact IEEE-754 double, then quantize rounds
    half-to-even — matching the platform default and ``format(value, ".12f")`` (asserted by the
    unit tests)."""
    if not math.isfinite(value):
        # Non-finite floats are not signable: json.dumps would emit NaN/Infinity (invalid per
        # RFC 8259), producing an unparseable signed payload (RCPT-A-002). Refuse at sign time.
        raise ValueError(f"non-finite float cannot be signed/canonicalized: {value!r}")
    if value == 0.0:
        # Normalize signed zero: -0.0 is a finite double that passes the check above, but Python
        # renders it "-0.000000000000" while JS (-0).toFixed(12) → "0.000000000000" (cross-tool
        # byte divergence), and SQLite's REAL column drops the sign bit so a -0.0 confidence would
        # sign as "-0..." yet read back +0.0 and fail prism's OWN verify. Collapse -0.0 → +0.0.
        value = 0.0
    with localcontext() as ctx:
        ctx.prec = _V5_DECIMAL_PREC
        quantized = Decimal(value).quantize(_V5_QUANTUM, rounding=ROUND_HALF_EVEN)
    return f"{quantized:.{_V5_FLOAT_PLACES}f}"


def _canonical_v5(receipt_data: dict[str, Any]) -> bytes:
    """schema_version == 5 canonical bytes — an RFC 8785 (JCS)-style profile a NON-Python tool can
    reproduce (the cross-tool verify promise). Full byte rules in the module docstring.

    Hand-rolled (not ``json.dumps``) so floats use the fixed-precision rule while structural/string
    escaping still follows RFC 8259 via ``json.dumps`` on each scalar string. ``bool`` is checked
    before ``int`` (``bool`` subclasses ``int``) so ``retryable`` is ``true``/``false`` not 1/0."""

    def enc(obj: Any) -> str:
        if obj is None:
            return "null"
        if isinstance(obj, bool):
            return "true" if obj else "false"
        if isinstance(obj, float):
            return _v5_number(obj)
        if isinstance(obj, int):
            return str(obj)
        if isinstance(obj, str):
            # RFC 8259 string escaping, but emit non-ASCII as literal UTF-8 (no \uXXXX).
            return json.dumps(obj, ensure_ascii=False)
        if isinstance(obj, dict):
            # Keys sorted by Unicode code point (Python's default str ordering), recursively.
            items = sorted(obj.items(), key=lambda kv: kv[0])
            return "{" + ",".join(f"{enc(k)}:{enc(v)}" for k, v in items) + "}"
        if isinstance(obj, list | tuple):
            return "[" + ",".join(enc(v) for v in obj) + "]"
        raise TypeError(f"value of type {type(obj).__name__!r} is not canonicalizable")

    return enc(receipt_data).encode("utf-8")


def _canonical_for(schema_version: int, receipt_data: dict[str, Any]) -> bytes:
    """Dispatch to the canonicalizer for a receipt's schema version. v5 → v5 (cross-tool format);
    everything at or below v4 (including unset/legacy) → v4. This is what keeps old receipts
    verifying after the v5 cutover: a stored v4 receipt is re-canonicalized with v4 bytes."""
    if schema_version >= 5:
        return _canonical_v5(receipt_data)
    return _canonical_v4(receipt_data)


def _compute_signature(receipt_data: dict[str, Any], secret: bytes) -> str:
    """HMAC-SHA256 over the v4 canonical representation (the legacy/HMAC test helper; v2/v3/v4
    receipts are all v4-canonicalized). Used by the schema-migration tests to forge legacy
    signatures over their own field-set."""
    return hmac.new(secret, _canonical_v4(receipt_data), hashlib.sha256).hexdigest()


def _reject_non_finite(name: str, value: float) -> None:
    """Refuse a NaN / ±Infinity numeric input at the create boundary (RCPT-A-002).

    confidence and pairwise_rho values are caller-influenced; a non-finite value would otherwise
    serialize (under v4's ``json.dumps``) to the bare literals ``NaN``/``Infinity`` — invalid per
    RFC 8259 — yielding a signed payload no standards-compliant verifier can parse."""
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number, got {value!r}")


def _dev_kid_untrusted(kid: str | None) -> bool:
    """Whether a receipt's ``kid`` is the WELL-KNOWN dev key and must NOT be trusted here.

    The dev Ed25519 seed is public, so anyone can forge a receipt bearing ``DEV_KID``. Signing
    with it is gated behind PRISM_DEV=1; this is the matching VERIFY-side guard (RCPT-A-003): a
    receipt with the dev kid is refused unless PRISM_DEV=1, while prism→prism dev round-trips keep
    working under PRISM_DEV=1. A non-dev kid (real key, or empty for HMAC) is unaffected."""
    return bool(kid) and kid == DEV_KID and not prism_dev_enabled()


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
        """Create and store a new receipt (always at the current schema version).

        Raises ``ValueError`` if ``confidence`` or any ``pairwise_rho`` value is non-finite
        (NaN / ±Infinity): such values would produce an invalid-JSON signed payload that no
        standards-compliant verifier could parse (RCPT-A-002), so they are refused at the boundary
        rather than silently signed.
        """
        _reject_non_finite("confidence", confidence)
        for key, rho in pairwise_rho.items():
            _reject_non_finite(f"pairwise_rho[{key!r}]", rho)

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
        signature = self._signer.sign(_canonical_for(CURRENT_SCHEMA_VERSION, sign_data))

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

        Reconstructs the signed payload at the receipt's own schema version (using that version's
        canonicalizer) and dispatches to the backend matching the receipt's recorded ``alg``
        (whitelisted — a receipt can never pick a verifier path we do not hold a key for). Legacy
        v1–v4 receipts (signed over their own field-set with v4 canonical bytes, alg defaulting to
        HMAC) still verify after the v5 cutover.
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
        alg = data.get("alg") or ALG_HMAC
        backend = self._verifiers.get(alg)
        if backend is None:
            # We hold no key for this algorithm — cannot verify (e.g. an Ed25519-only store asked
            # to verify a legacy HMAC receipt without the HMAC secret).
            return False
        if _dev_kid_untrusted(data.get("kid")):
            # Well-known dev key is forgeable by anyone; refuse it outside PRISM_DEV (RCPT-A-003).
            return False
        try:
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
                artifact_type=data.get("artifact_type", "code"),
                retrieval_pins=json.loads(data.get("retrieval_pins") or "[]"),
                alg=alg,
                kid=data.get("kid", ""),
            )
            signature = data["signature"]
            canonical = _canonical_for(schema_version, sign_data)
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            # A malformed / incomplete receipt is simply not validly signed — never a crash.
            # (Includes a v5 receipt whose float fields are non-finite — unparseable, so not valid.)
            return False
        return backend.verify(canonical, signature)

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
        try:
            backend = Ed25519Backend.from_public_pem(public_key_pem)
        except SigningSecretError:
            return False  # an unparseable public key cannot verify anything
    if backend is None:
        return False
    if _dev_kid_untrusted(receipt.get("kid")):
        # The well-known dev key is forgeable by anyone; refuse it outside PRISM_DEV (RCPT-A-003).
        return False

    # A malformed / incomplete caller-supplied receipt is simply not validly signed — never crash
    # (the HTTP /verify-receipt handler relies on this to keep its RFC 9457 contract).
    try:
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
        signature = receipt["signature"]
        canonical = _canonical_for(schema_version, sign_data)
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        # Includes a v5 receipt with non-finite floats — unparseable, hence not validly signed.
        return False
    return backend.verify(canonical, signature)
