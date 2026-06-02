"""Receipt signing backends — HMAC (legacy/explicit) + Ed25519 (production default, v0.4).

v0.4 makes Ed25519 the production default so a DIFFERENT tool can verify a prism receipt with
prism's PUBLIC key — no shared secret. This closes role-os's named gap ("cryptographic
verification of prism's inner HMAC needs a shared key"). HMAC is retained for legacy receipts
and explicit opt-in (``PRISM_SIGNING_SECRET``), and every receipt records its ``alg`` so a
verifier dispatches on the algorithm the receipt was signed with (version-aware).

Honest ceiling (threat model): an on-disk private key is forgeable by a local-root attacker,
exactly like the on-disk HMAC secret. Ed25519 buys THIRD-PARTY VERIFIABILITY, not stronger
anti-forgery. HSM-held keys + an append-only transparency log are the path to genuine
tamper-resistance (see ``design/05-http-and-receipts.md`` §D and SECURITY.md).
"""

from __future__ import annotations

import hashlib
import hmac
import os
from abc import ABC, abstractmethod
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

ALG_HMAC = "HMAC-SHA256"
ALG_ED25519 = "Ed25519"

# Deterministic dev seed (32 bytes) — the Ed25519 analogue of the HMAC dev secret. Used ONLY
# when PRISM_DEV=1 and nothing else is configured; the resolver refuses it in production.
_DEV_ED25519_SEED = b"prism-dev-ed25519-seed-0123456\x00\x01"
# Legacy dev HMAC secret (matches the pre-v0.4 dev default) — registered as a VERIFY-ONLY
# backend under PRISM_DEV so receipts written by an older prism dev build still verify.
_DEV_HMAC_SECRET = b"prism-dev-secret"


class SigningSecretError(RuntimeError):
    """Raised when no usable signing key/secret is configured."""


class SigningBackend(ABC):
    """A receipt-signing algorithm. ``alg`` is recorded in the receipt; ``kid`` names the key."""

    alg: str
    kid: str

    @abstractmethod
    def sign(self, payload: bytes) -> str:
        """Return a hex signature over ``payload``."""

    @abstractmethod
    def verify(self, payload: bytes, signature: str) -> bool:
        """Constant-time / cryptographic check of ``signature`` over ``payload``."""


class HmacBackend(SigningBackend):
    """Symmetric HMAC-SHA256. Verifiable only by a holder of the shared secret (legacy)."""

    alg = ALG_HMAC

    def __init__(self, secret: bytes) -> None:
        self._secret = secret
        self.kid = ""  # symmetric — no published key id

    def sign(self, payload: bytes) -> str:
        return hmac.new(self._secret, payload, hashlib.sha256).hexdigest()

    def verify(self, payload: bytes, signature: str) -> bool:
        return hmac.compare_digest(self.sign(payload), signature)


def _kid_for(public_key: Ed25519PublicKey) -> str:
    """A short, stable key id = a prefix of the SHA-256 of the raw public key."""
    raw = public_key.public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    return "ed25519-" + hashlib.sha256(raw).hexdigest()[:16]


class Ed25519Backend(SigningBackend):
    """Asymmetric Ed25519 (RFC 8032). Verifiable with only the PUBLIC key — the cross-tool path."""

    alg = ALG_ED25519

    def __init__(
        self,
        private_key: Ed25519PrivateKey | None,
        public_key: Ed25519PublicKey | None = None,
    ) -> None:
        if private_key is None and public_key is None:
            raise SigningSecretError("Ed25519 backend needs a private or public key")
        self._private = private_key
        self._public = public_key if public_key is not None else private_key.public_key()  # type: ignore[union-attr]
        self.kid = _kid_for(self._public)

    def sign(self, payload: bytes) -> str:
        if self._private is None:
            raise SigningSecretError("Ed25519 backend is verify-only (no private key)")
        return self._private.sign(payload).hex()

    def verify(self, payload: bytes, signature: str) -> bool:
        try:
            self._public.verify(bytes.fromhex(signature), payload)
            return True
        except (InvalidSignature, ValueError):
            return False

    def public_key_pem(self) -> str:
        return self._public.public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        ).decode()

    @classmethod
    def dev(cls) -> Ed25519Backend:
        return cls(Ed25519PrivateKey.from_private_bytes(_DEV_ED25519_SEED))

    @classmethod
    def from_private_pem(cls, pem_or_path: str) -> Ed25519Backend:
        key = serialization.load_pem_private_key(_read_key_material(pem_or_path), password=None)
        if not isinstance(key, Ed25519PrivateKey):
            raise SigningSecretError("signing key is not an Ed25519 private key")
        return cls(key)

    @classmethod
    def from_public_pem(cls, pem_or_path: str) -> Ed25519Backend:
        key = serialization.load_pem_public_key(_read_key_material(pem_or_path))
        if not isinstance(key, Ed25519PublicKey):
            raise SigningSecretError("public key is not an Ed25519 public key")
        return cls(private_key=None, public_key=key)


def _read_key_material(value: str) -> bytes:
    """Accept either an inline PEM string or a filesystem path to a PEM file."""
    if "-----BEGIN" in value:
        return value.encode()
    path = Path(value).expanduser()
    if path.is_file():
        return path.read_bytes()
    raise SigningSecretError(
        f"signing key is neither inline PEM nor a readable file: {value!r}"
    )


def generate_keypair() -> tuple[str, str, str]:
    """Generate a fresh Ed25519 keypair. Returns ``(private_pem, public_pem, kid)``."""
    private = Ed25519PrivateKey.generate()
    backend = Ed25519Backend(private)
    private_pem = private.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    return private_pem, backend.public_key_pem(), backend.kid


def resolve_backends(
    signing_secret: bytes | None = None,
    signing_key: str | Ed25519PrivateKey | Ed25519Backend | None = None,
) -> tuple[SigningBackend, dict[str, SigningBackend]]:
    """Resolve the active signing backend plus a verifier registry (``alg -> backend``).

    Priority (Ed25519 is the v0.4 production default):

    1. Explicit ``signing_key`` / ``signing_secret`` args (no env mixing — the test/embedding path).
    2. ``PRISM_SIGNING_KEY`` (Ed25519 private PEM or path) → Ed25519.
    3. ``PRISM_SIGNING_SECRET`` → HMAC (explicit legacy).
    4. ``PRISM_DEV=1`` → a built-in dev Ed25519 key (the new zero-config dev default), plus a
       verify-only dev HMAC backend so older dev receipts still verify.
    5. Otherwise raise.

    The verifier registry holds every backend we have key material for, so legacy HMAC receipts
    still verify even when new receipts are signed with Ed25519 (the version-aware guarantee).
    """
    ed: Ed25519Backend | None = None
    mac: HmacBackend | None = None

    if signing_key is not None or signing_secret is not None:
        if signing_key is not None:
            ed = _backend_from_signing_key(signing_key)
        if signing_secret is not None:
            mac = HmacBackend(signing_secret)
    else:
        env_key = os.environ.get("PRISM_SIGNING_KEY")
        env_secret = os.environ.get("PRISM_SIGNING_SECRET")
        if env_key:
            ed = Ed25519Backend.from_private_pem(env_key)
        if env_secret:
            mac = HmacBackend(env_secret.encode())
        if ed is None and mac is None and os.environ.get("PRISM_DEV") == "1":
            ed = Ed25519Backend.dev()
            mac = HmacBackend(_DEV_HMAC_SECRET)  # verify legacy dev receipts

    active: SigningBackend | None = ed or mac
    if active is None:
        raise SigningSecretError(
            "No receipt signing key configured. Set PRISM_SIGNING_KEY (Ed25519 private key — "
            "recommended; run `prism keygen`), PRISM_SIGNING_SECRET (HMAC, legacy), pass "
            "signing_key=/signing_secret=, or set PRISM_DEV=1 for local development."
        )

    verifiers: dict[str, SigningBackend] = {}
    if mac is not None:
        verifiers[ALG_HMAC] = mac
    if ed is not None:
        verifiers[ALG_ED25519] = ed
    return active, verifiers


def _backend_from_signing_key(
    signing_key: str | Ed25519PrivateKey | Ed25519Backend,
) -> Ed25519Backend:
    if isinstance(signing_key, Ed25519Backend):
        return signing_key
    if isinstance(signing_key, Ed25519PrivateKey):
        return Ed25519Backend(signing_key)
    return Ed25519Backend.from_private_pem(signing_key)
