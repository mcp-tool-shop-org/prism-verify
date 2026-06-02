"""API-key auth + abuse controls for the prism HTTP surface (v0.4).

A single scoped bearer API key is the OWASP API2:2023-sanctioned mechanism for an M2M service
(no delegated-user problem → no OAuth in v0.4). Keys are ``prism_``-prefixed, hashed at rest
(only SHA-256 hashes live in ``PRISM_API_KEYS``), and constant-time compared. The primary abuse
control for an LLM-backed endpoint is COST/SIZE back-pressure (OWASP LLM10 "denial of wallet"),
not request count: an artifact size cap + a per-key rate limit + a *stricter* failed-auth limiter
so key-guessing costs ~0 compute. See ``design/05`` §B.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import time
from collections.abc import Callable

from prism.http.errors import ProblemError

API_KEY_PREFIX = "prism_"


def hash_key(key: str) -> str:
    """SHA-256 hex of an API key — what lives in config (``PRISM_API_KEYS``), never the raw key."""
    return hashlib.sha256(key.encode()).hexdigest()


def generate_api_key() -> tuple[str, str]:
    """Generate a fresh ``prism_``-prefixed key. Returns ``(key, sha256_hash)``.

    Give the key to the client; put the hash in ``PRISM_API_KEYS``.
    """
    key = API_KEY_PREFIX + secrets.token_urlsafe(32)
    return key, hash_key(key)


def load_key_hashes(value: str | None = None) -> set[str]:
    """Parse ``PRISM_API_KEYS`` (comma-separated SHA-256 hashes)."""
    raw = value if value is not None else os.environ.get("PRISM_API_KEYS", "")
    return {part.strip() for part in raw.split(",") if part.strip()}


class TokenBucket:
    """A monotonic token bucket. ``clock`` is injectable so tests exhaust it deterministically."""

    def __init__(
        self,
        capacity: float,
        refill_per_s: float,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self.capacity = capacity
        self.refill_per_s = refill_per_s
        self._clock = clock or time.monotonic
        self._tokens = capacity
        self._last = self._clock()

    def _refill(self) -> None:
        now = self._clock()
        elapsed = now - self._last
        self._last = now
        self._tokens = min(self.capacity, self._tokens + elapsed * self.refill_per_s)

    def try_consume(self, amount: float = 1.0) -> bool:
        """Consume ``amount`` tokens; return True if consumed, False if rate-limited."""
        self._refill()
        if self._tokens >= amount:
            self._tokens -= amount
            return True
        return False

    @property
    def remaining(self) -> int:
        self._refill()
        return int(self._tokens)

    def retry_after_s(self, amount: float = 1.0) -> int:
        self._refill()
        if self._tokens >= amount or self.refill_per_s <= 0:
            return 0
        return max(1, int((amount - self._tokens) / self.refill_per_s) + 1)


class Authenticator:
    """Validates bearer keys and applies per-key + failed-auth rate limits."""

    def __init__(
        self,
        key_hashes: set[str],
        *,
        allow_no_auth: bool = False,
        requests_per_minute: int = 60,
        failed_auth_per_minute: int = 5,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._key_hashes = key_hashes
        self._allow_no_auth = allow_no_auth
        self._rpm = requests_per_minute
        self._fpm = failed_auth_per_minute
        self._clock = clock or time.monotonic
        self._buckets: dict[str, TokenBucket] = {}
        self._fail_buckets: dict[str, TokenBucket] = {}

    def _bucket(self, store: dict[str, TokenBucket], key: str, rpm: int) -> TokenBucket:
        bucket = store.get(key)
        if bucket is None:
            bucket = TokenBucket(capacity=rpm, refill_per_s=rpm / 60.0, clock=self._clock)
            store[key] = bucket
        return bucket

    def authenticate(self, authorization: str | None, client_ip: str) -> str:
        """Return the caller's key-hash (the rate-limit identity), or raise ``ProblemError``.

        Fail-closed: if no keys are configured and ``PRISM_HTTP_ALLOW_NO_AUTH`` is unset, every
        request is refused so an expensive endpoint is never accidentally left open.
        """
        if not self._key_hashes:
            if self._allow_no_auth:
                return "anonymous"
            raise ProblemError(
                401,
                "no-auth-configured",
                "Unauthorized",
                "Server has no API keys configured. Set PRISM_API_KEYS, or set "
                "PRISM_HTTP_ALLOW_NO_AUTH=1 to allow unauthenticated local use.",
            )

        # Stricter failed-auth limiter (per IP) — a wrong/missing key must cost ~0 compute.
        fail_bucket = self._bucket(self._fail_buckets, client_ip, self._fpm)

        if not authorization or not authorization.startswith("Bearer "):
            self._charge_failure(fail_bucket)
            raise ProblemError(
                401, "unauthorized", "Unauthorized", "Missing or malformed Authorization header."
            )
        presented = hash_key(authorization[len("Bearer ") :])
        if not any(hmac.compare_digest(presented, kh) for kh in self._key_hashes):
            self._charge_failure(fail_bucket)
            raise ProblemError(401, "unauthorized", "Unauthorized", "Invalid API key.")
        return presented

    def _charge_failure(self, fail_bucket: TokenBucket) -> None:
        if not fail_bucket.try_consume():
            raise ProblemError(
                429,
                "too-many-failed-auth",
                "Too Many Requests",
                "Too many failed authentication attempts.",
                headers={"Retry-After": str(fail_bucket.retry_after_s())},
            )

    def check_rate(self, identity: str) -> dict[str, str]:
        """Charge one request against the caller's rate limit. Raises 429 on exhaustion.

        Returns RateLimit headers to attach to the successful response (back-pressure is part of
        the contract — emitted on success too, per the IETF RateLimit draft).
        """
        bucket = self._bucket(self._buckets, identity, self._rpm)
        if not bucket.try_consume():
            retry = bucket.retry_after_s()
            raise ProblemError(
                429,
                "rate-limited",
                "Too Many Requests",
                "Per-key rate limit exceeded.",
                headers={
                    "Retry-After": str(retry),
                    "RateLimit": f"limit={self._rpm}, remaining=0, reset={retry}",
                },
            )
        return {"RateLimit": f"limit={self._rpm}, remaining={bucket.remaining}, reset=60"}
